from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import engine, Base, get_db
from backend.models import Complaint, ActivityLog
from backend.agent import classify_complaint
from backend.scheduler import start_scheduler, stop_scheduler, get_sla_duration

# Initialize SQLite database tables
Base.metadata.create_all(bind=engine)


# FastAPI Lifespan to manage background scheduler lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    # App Startup: Start APScheduler
    start_scheduler()
    yield
    # App Shutdown: Gracefully stop APScheduler
    stop_scheduler()


app = FastAPI(
    title="CampusResolve API",
    description="Agentic grievance resolution and automated escalation platform for colleges",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initial Authority Mapping based on classified Category
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


# --- Endpoints ---

@app.get("/")
def health_check():
    """Health check endpoint."""
    return {"status": "CampusResolve agent running"}


@app.post("/complaints", response_model=ComplaintOut, status_code=201)
def create_complaint(payload: ComplaintCreate, db: Session = Depends(get_db)):
    """
    Create a new complaint, call LLM classification, route to initial authority,
    calculate SLA deadline (supporting DEBUG_TIME_SCALE), enforce safety flags, and log the activity.
    """
    created_at = datetime.utcnow()

    # 1. Call AI Classifier (Groq / Mock fallback)
    classification = classify_complaint(payload.text)
    category = classification.get("category", "infrastructure").lower()
    urgency = classification.get("urgency", "medium").lower()
    reasoning = classification.get("reasoning", "")

    # 2. Determine Initial Assigned Authority
    assigned_authority = AUTHORITY_MAP.get(category, "Estate Office")

    # 3. Apply Special Harassment Rule
    no_auto_escalation = False
    if category == "harassment":
        urgency = "high"
        assigned_authority = "Counseling Cell"
        no_auto_escalation = True

    # 4. Calculate SLA Deadline with DEBUG_TIME_SCALE support
    sla_delta = get_sla_duration(urgency)
    sla_deadline = created_at + sla_delta

    # 5. Create Complaint Record
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

    # 6. Log Activity Entry
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

    return complaint


@app.get("/complaints", response_model=List[ComplaintOut])
def list_complaints(db: Session = Depends(get_db)):
    """List all complaints."""
    return db.query(Complaint).order_by(Complaint.created_at.desc()).all()


@app.get("/complaints/{id}", response_model=ComplaintDetailOut)
def get_complaint(id: int, db: Session = Depends(get_db)):
    """Get a single complaint along with its activity log."""
    complaint = db.query(Complaint).filter(Complaint.id == id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return complaint


@app.patch("/complaints/{id}/resolve", response_model=ComplaintOut)
def resolve_complaint(id: int, db: Session = Depends(get_db)):
    """Mark a complaint as resolved and record the activity log."""
    complaint = db.query(Complaint).filter(Complaint.id == id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    complaint.status = "resolved"
    complaint.resolved_at = datetime.utcnow()

    log_entry = ActivityLog(
        complaint_id=complaint.id,
        action="RESOLVED",
        details="Complaint marked as resolved by authority.",
        timestamp=datetime.utcnow(),
    )
    db.add(log_entry)
    db.commit()
    db.refresh(complaint)

    return complaint
