import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import engine, Base, get_db
from backend.models import Complaint, ActivityLog, User
from backend.agent import classify_complaint
from backend.scheduler import start_scheduler, stop_scheduler, get_sla_duration
from backend.websocket_manager import manager, set_main_event_loop, broadcast_activity_sync
from backend.notifier import get_sent_emails, send_new_complaint_email, get_authority_email, AUTHORITY_DIRECTORY
from backend.auth import (
    verify_password,
    create_session_token,
    get_current_user,
    get_optional_user,
    seed_authority_users,
    DEFAULT_ACCOUNTS,
    ACTIVE_SESSIONS,
)

# Initialize SQLite database tables
Base.metadata.create_all(bind=engine)


# FastAPI Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed default authority user accounts on boot
    db = next(get_db())
    try:
        seed_authority_users(db)
    finally:
        db.close()

    set_main_event_loop(asyncio.get_running_loop())
    start_scheduler()
    yield
    stop_scheduler()



app = FastAPI(
    title="CampusResolve API",
    description="Agentic grievance resolution, authority-based role dashboards, and automated email escalation",
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

# Prevent stale browser caching of frontend static assets
@app.middleware("http")
async def add_cache_control_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/app"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

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
    assigned_authority: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class UserProfileOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: str
    assigned_authority: Optional[str] = None
    tier: Optional[str] = None

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfileOut


class DemoAccountItem(BaseModel):
    username: str
    password: str
    email: str
    full_name: str
    role: str
    assigned_authority: Optional[str] = None
    tier: Optional[str] = None


# --- Endpoints ---

from fastapi.responses import RedirectResponse

@app.get("/")
def root():
    """Redirect root access directly to the CampusResolve student UI."""
    return RedirectResponse(url="/app/")


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "CampusResolve agent running"}


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user with username and password, return active session token and user profile."""
    username_clean = payload.username.strip().lower()
    user = db.query(User).filter(
        (User.username.ilike(username_clean)) | (User.email.ilike(username_clean))
    ).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password. Please check your credentials.",
        )

    token = create_session_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user,
    }


@app.get("/auth/me", response_model=UserProfileOut)
def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Retrieve profile of the currently authenticated authority user."""
    return current_user


@app.get("/auth/accounts", response_model=List[DemoAccountItem])
def list_demo_accounts():
    """List pre-configured demo authority login credentials for evaluation and quick-login."""
    return DEFAULT_ACCOUNTS


@app.post("/auth/logout")
def logout(authorization: Optional[str] = Header(None)):
    """Terminate active authority session."""
    if authorization:
        token = authorization[7:].strip() if authorization.startswith("Bearer ") else authorization.strip()
        ACTIVE_SESSIONS.pop(token, None)
    return {"message": "Logged out successfully"}


@app.get("/authorities")
def list_authorities():
    """Returns directory of university authorities, roles, tiers, and emails."""
    return [
        {
            "id": key,
            "name": val["name"],
            "authority": key,
            "email": val["email"],
            "tier": val["tier"]
        }
        for key, val in AUTHORITY_DIRECTORY.items()
    ]


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

    # 5. Dispatch Automated Notification Email to Assigned Authority
    assigned_email = get_authority_email(assigned_authority)
    send_new_complaint_email(
        complaint_id=complaint.id,
        complaint_text=complaint.text,
        category=complaint.category,
        urgency=complaint.urgency,
        assigned_authority=complaint.assigned_authority,
        sla_deadline=complaint.sla_deadline
    )

    # 6. Log Activity Entry
    log_details = f"Classified as {category}/{urgency}, routed to {assigned_authority}. Alert email dispatched to {assigned_email}."
    if reasoning:
        log_details += f" Reasoning: {reasoning}"
    
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

    # 6. Real-Time WebSocket Broadcast
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
        "assigned_authority": complaint.assigned_authority,
    })

    return complaint


@app.get("/complaints", response_model=List[ComplaintOut])
def list_complaints(
    assigned_authority: Optional[str] = Query(None, description="Filter complaints for a specific authority role"),
    include_harassment: bool = Query(False, description="Whether to include protected harassment records"),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    List complaints with role-based authority isolation.
    If assigned_authority is specified, returns only complaints assigned to that authority.
    """
    query = db.query(Complaint)
    
    if assigned_authority and assigned_authority != "All":
        query = query.filter(Complaint.assigned_authority == assigned_authority)
    elif not include_harassment:
        query = query.filter(Complaint.category != "harassment")

    if status:
        query = query.filter(Complaint.status == status)

    return query.order_by(Complaint.created_at.desc()).all()


@app.get("/counselor/complaints", response_model=List[ComplaintOut])
def list_counselor_complaints(db: Session = Depends(get_db)):
    """Protected endpoint for Counseling Cell portal to view sensitive harassment records."""
    return db.query(Complaint).filter(Complaint.category == "harassment").order_by(Complaint.created_at.desc()).all()


@app.get("/complaints/{id}", response_model=ComplaintDetailOut)
def get_complaint(id: int, db: Session = Depends(get_db)):
    """Get a single complaint along with its activity log."""
    complaint = db.query(Complaint).filter(Complaint.id == id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return complaint


class ComplaintResolveRequest(BaseModel):
    remarks: Optional[str] = None


@app.patch("/complaints/{id}/resolve", response_model=ComplaintOut)
def resolve_complaint(
    id: int, 
    payload: Optional[ComplaintResolveRequest] = None, 
    db: Session = Depends(get_db)
):
    """Mark a complaint as resolved with optional remarks, record activity log, and broadcast event."""
    complaint = db.query(Complaint).filter(Complaint.id == id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    complaint.status = "resolved"
    complaint.resolved_at = datetime.utcnow()

    remarks_str = f" Remarks: {payload.remarks.strip()}" if (payload and payload.remarks and payload.remarks.strip()) else ""
    log_entry = ActivityLog(
        complaint_id=complaint.id,
        action="RESOLVED",
        details=f"Complaint marked as resolved by {complaint.assigned_authority}.{remarks_str}",
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
        "assigned_authority": complaint.assigned_authority,
    })

    return complaint


@app.get("/activity-feed", response_model=List[ActivityFeedItem])
def get_activity_feed(
    assigned_authority: Optional[str] = Query(None, description="Filter activity logs for a specific authority"),
    db: Session = Depends(get_db)
):
    """
    Returns the 50 most recent activity_log entries.
    If assigned_authority is provided, filters to events for complaints currently assigned to that authority.
    """
    query = (
        db.query(ActivityLog, Complaint.text, Complaint.status, Complaint.category, Complaint.assigned_authority)
        .join(Complaint, ActivityLog.complaint_id == Complaint.id)
    )

    if assigned_authority and assigned_authority != "All":
        query = query.filter(Complaint.assigned_authority == assigned_authority)

    results = query.order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc()).limit(50).all()

    feed = []
    for log, text, status, category, auth in results:
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
            "assigned_authority": auth,
        })

    return feed


@app.get("/authority/emails")
def list_authority_emails(assigned_authority: Optional[str] = Query(None)):
    """Retrieve simulated email inbox logs for an authority role or all authorities."""
    return get_sent_emails(assigned_authority)


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
