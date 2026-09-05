import asyncio
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import engine, Base, get_db
from backend.models import Complaint, ActivityLog
from backend.agent import classify_complaint
from backend.scheduler import start_scheduler, stop_scheduler, get_sla_duration
from backend.websocket_manager import manager, set_main_event_loop, broadcast_activity_sync

# Initialize SQLite database tables
Base.metadata.create_all(bind=engine)


# FastAPI Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    set_main_event_loop(asyncio.get_running_loop())
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="CampusResolve API",
    description="Agentic grievance resolution, real-time monitoring, and protected counselor portal",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount frontend directory for browser access
app.mount("/app", StaticFiles(directory="frontend", html=True), name="frontend")

# Authority Mapping
AUTHORITY_MAP = {
    "hostel": "Warden",
    "mess": "Mess Committee",
    "academic": "HOD",
    "infrastructure": "Estate Office",
    "harassment": "Counseling Cell",
}


# --- Pydantic Schemas ---

class ComplaintCreate(BaseModel):
    text: str


class ActivityLogOut(BaseModel):
    id: int
    complaint_id: int
    action: str
    details: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True


class ComplaintOut(BaseModel):
    id: int
    text: str
    category: Optional[str] = None
    urgency: Optional[str] = None
    status: str
    assigned_authority: Optional[str] = None
    escalation_level: int
    no_auto_escalation: bool = False
    created_at: datetime
    sla_deadline: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ComplaintDetailOut(ComplaintOut):
    activity_logs: List[ActivityLogOut] = []


class ActivityFeedItem(BaseModel):
    id: int
    complaint_id: int
    action: str
    details: Optional[str] = None
    timestamp: str
    complaint_text: str
    complaint_status: str


# --- Endpoints ---

@app.get("/")
def health_check():
    """Health check endpoint."""
    return {"status": "CampusResolve agent running"}


@app.post("/complaints", response_model=ComplaintOut, status_code=201)
def create_complaint(payload: ComplaintCreate, db: Session = Depends(get_db)):
    """
    Create a new complaint, execute AI classification, route to appropriate authority,
    calculate SLA deadline, enforce harassment safety flags, log activity, and broadcast event.
    """
    created_at = datetime.utcnow()

    # 1. Call AI Classifier (with timeout + mock fallback protection)
    classification = classify_complaint(payload.text)
    category = classification.get("category", "infrastructure").lower()
    urgency = classification.get("urgency", "medium").lower()
    reasoning = classification.get("reasoning", "")

    # 2. Determine Authority & Enforce Harassment Safety Guardrails
    no_auto_escalation = False
    if category == "harassment":
        # CRITICAL: Harassment complaints are locked to high urgency, Counseling Cell, and immune from auto-escalation
        urgency = "high"
        assigned_authority = "Counseling Cell"
        no_auto_escalation = True
    else:
        assigned_authority = AUTHORITY_MAP.get(category, "Estate Office")

    # 3. Calculate SLA Deadline with DEBUG_TIME_SCALE support
    sla_delta = get_sla_duration(urgency)
    sla_deadline = created_at + sla_delta

    # 4. Create Complaint Record
    complaint = Complaint(
        text=payload.text,
        category=category,
        urgency=urgency,
        status="open",
        assigned_authority=assigned_authority,
        escalation_level=0,
        no_auto_escalation=no_auto_escalation,
        created_at=created_at,
        sla_deadline=sla_deadline,
        resolved_at=None,
    )
    db.add(complaint)
    db.flush()

    # 5. Log Activity Entry
    log_details = f"Classified as {category}/{urgency}, routed to {assigned_authority}. Reasoning: {reasoning}" if reasoning else f"Classified as {category}/{urgency}, routed to {assigned_authority}"
    
    activity_entry = ActivityLog(
        complaint_id=complaint.id,
        action="CLASSIFICATION",
        details=log_details,
        timestamp=datetime.utcnow(),
    )
    db.add(activity_entry)
    db.commit()
    db.refresh(complaint)
    db.refresh(activity_entry)

    # 6. Real-Time WebSocket Broadcast (Mask text if harassment for public privacy)
    if category == "harassment":
        display_text = "[CONFIDENTIAL - ROUTED TO COUNSELING CELL]"
    else:
        display_text = (complaint.text[:60] + "...") if len(complaint.text) > 60 else complaint.text

    broadcast_activity_sync({
        "id": activity_entry.id,
        "complaint_id": complaint.id,
        "action": activity_entry.action,
        "details": activity_entry.details,
        "timestamp": activity_entry.timestamp.isoformat(),
        "complaint_text": display_text,
        "complaint_status": complaint.status,
    })

    return complaint


@app.get("/complaints", response_model=List[ComplaintOut])
def list_complaints(
    include_harassment: bool = Query(False, description="Whether to include protected harassment records"),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    List complaints for general dashboard.
    By default, excludes confidential harassment records to prevent public dashboard leakage.
    """
    query = db.query(Complaint)
    if not include_harassment:
        query = query.filter(Complaint.category != "harassment")
    if status:
        query = query.filter(Complaint.status == status)

    return query.order_by(Complaint.created_at.desc()).all()


@app.get("/counselor/complaints", response_model=List[ComplaintOut])
def list_counselor_complaints(db: Session = Depends(get_db)):
    """
    Protected endpoint for Counseling Cell portal to view sensitive harassment records.
    """
    return db.query(Complaint).filter(Complaint.category == "harassment").order_by(Complaint.created_at.desc()).all()


@app.get("/complaints/{id}", response_model=ComplaintDetailOut)
def get_complaint(id: int, db: Session = Depends(get_db)):
    """Get a single complaint along with its activity log."""
    complaint = db.query(Complaint).filter(Complaint.id == id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return complaint


@app.patch("/complaints/{id}/resolve", response_model=ComplaintOut)
def resolve_complaint(id: int, db: Session = Depends(get_db)):
    """Mark a complaint as resolved, record activity log, and broadcast event."""
    complaint = db.query(Complaint).filter(Complaint.id == id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    complaint.status = "resolved"
    complaint.resolved_at = datetime.utcnow()

    log_entry = ActivityLog(
        complaint_id=complaint.id,
        action="RESOLVED",
        details=f"Complaint marked as resolved by {complaint.assigned_authority}.",
        timestamp=datetime.utcnow(),
    )
    db.add(log_entry)
    db.commit()
    db.refresh(complaint)
    db.refresh(log_entry)

    # Broadcast resolution event
    if complaint.category == "harassment":
        display_text = "[CONFIDENTIAL - ROUTED TO COUNSELING CELL]"
    else:
        display_text = (complaint.text[:60] + "...") if len(complaint.text) > 60 else complaint.text

    broadcast_activity_sync({
        "id": log_entry.id,
        "complaint_id": complaint.id,
        "action": log_entry.action,
        "details": log_entry.details,
        "timestamp": log_entry.timestamp.isoformat(),
        "complaint_text": display_text,
        "complaint_status": complaint.status,
    })

    return complaint


@app.get("/activity-feed", response_model=List[ActivityFeedItem])
def get_activity_feed(db: Session = Depends(get_db)):
    """
    Returns the 50 most recent activity_log entries across all complaints.
    Masks sensitive text for harassment records in public feeds.
    """
    results = (
        db.query(ActivityLog, Complaint.text, Complaint.status, Complaint.category)
        .join(Complaint, ActivityLog.complaint_id == Complaint.id)
        .order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc())
        .limit(50)
        .all()
    )

    feed = []
    for log, text, status, category in results:
        raw_text = text or ""
        if category == "harassment":
            display_text = "[CONFIDENTIAL - ROUTED TO COUNSELING CELL]"
        else:
            display_text = (raw_text[:60] + "...") if len(raw_text) > 60 else raw_text

        feed.append({
            "id": log.id,
            "complaint_id": log.complaint_id,
            "action": log.action,
            "details": log.details,
            "timestamp": log.timestamp.isoformat() if log.timestamp else datetime.utcnow().isoformat(),
            "complaint_text": display_text,
            "complaint_status": status or "open",
        })

    return feed


@app.websocket("/ws/activity")
async def websocket_activity_feed(websocket: WebSocket):
    """WebSocket endpoint pushing real-time activity stream events."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
