from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import engine, Base, get_db
from backend.models import Complaint, ActivityLog
from backend.agent import agent

# Initialize SQLite database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="CampusResolve API",
    description="Agentic grievance resolution and complaint tracking system for colleges",
    version="1.0.0"
)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    """Create a new complaint with text and trigger automated agent analysis."""
    # Analyze text using agent triage
    analysis = agent.analyze(payload.text)

    complaint = Complaint(
        text=payload.text,
        category=analysis["category"],
        urgency=analysis["urgency"],
        status="open",
        assigned_authority=analysis["assigned_authority"],
        escalation_level=0,
        created_at=datetime.utcnow(),
        sla_deadline=analysis["sla_deadline"],
        resolved_at=None,
    )
    db.add(complaint)
    db.flush()

    # Log initial creation in activity_log
    log_entry = ActivityLog(
        complaint_id=complaint.id,
        action="CREATED",
        details=f"Complaint lodged. Triaged to category '{analysis['category']}' with urgency '{analysis['urgency']}' and assigned to '{analysis['assigned_authority']}'.",
        timestamp=datetime.utcnow(),
    )
    db.add(log_entry)
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
