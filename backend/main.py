import os
import uuid
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from backend.database import engine, Base, get_db
from backend.models import Grievance, GrievanceLog, GrievanceStatus, PriorityLevel, GrievanceCategory
from backend.agent import agent
from backend.scheduler import check_and_escalate_grievances

# Initialize Database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="CampusResolve API",
    description="Agentic grievance resolution and auto-triage platform for educational institutions",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Schemas ---
class GrievanceCreate(BaseModel):
    student_name: str
    student_email: str
    student_id: Optional[str] = None
    title: str
    description: str


class GrievanceResponse(BaseModel):
    id: int
    ticket_id: str
    student_name: str
    student_email: str
    student_id: Optional[str]
    title: str
    description: str
    category: str
    priority: str
    status: str
    assigned_department: Optional[str]
    ai_summary: Optional[str]
    suggested_action: Optional[str]
    created_at: str
    sla_deadline: Optional[str]

    class Config:
        from_attributes = True


# --- Endpoints ---

@app.get("/")
def health_check():
    """Health check endpoint requested in specifications."""
    return {"status": "CampusResolve agent running"}


@app.post("/api/grievances", response_model=dict)
def submit_grievance(payload: GrievanceCreate, db: Session = Depends(get_db)):
    """Submit a new grievance which triggers autonomous agent triage."""
    ticket_id = f"CR-{uuid.uuid4().hex[:8].upper()}"
    
    # Run Agent Analysis
    analysis = agent.analyze_grievance(title=payload.title, description=payload.description)
    
    # Create Grievance Record
    grievance = Grievance(
        ticket_id=ticket_id,
        student_name=payload.student_name,
        student_email=payload.student_email,
        student_id=payload.student_id,
        title=payload.title,
        description=payload.description,
        category=analysis["category"],
        priority=analysis["priority"],
        status=analysis["initial_status"],
        assigned_department=analysis["assigned_department"],
        sentiment_score=analysis["sentiment_score"],
        ai_summary=analysis["ai_summary"],
        suggested_action=analysis["suggested_action"],
        sla_deadline=analysis["sla_deadline"]
    )
    db.add(grievance)
    db.flush()

    # Log Agent Action
    initial_log = GrievanceLog(
        grievance_id=grievance.id,
        action="TRIAGE_COMPLETED",
        actor="CampusResolve_AI_Agent",
        details=f"Assigned to {analysis['assigned_department']} with priority {analysis['priority'].value}. Suggested action: {analysis['suggested_action']}"
    )
    db.add(initial_log)
    db.commit()
    db.refresh(grievance)

    return {
        "success": True,
        "ticket_id": grievance.ticket_id,
        "status": grievance.status.value,
        "category": grievance.category.value,
        "priority": grievance.priority.value,
        "assigned_department": grievance.assigned_department,
        "ai_summary": grievance.ai_summary,
        "suggested_action": grievance.suggested_action,
        "sla_deadline": grievance.sla_deadline.isoformat() if grievance.sla_deadline else None
    }


@app.get("/api/grievances")
def list_grievances(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Retrieve all grievances with optional filters for the Admin/Staff Dashboard."""
    query = db.query(Grievance)
    if status:
        query = query.filter(Grievance.status == status)
    if priority:
        query = query.filter(Grievance.priority == priority)
        
    grievances = query.order_by(Grievance.created_at.desc()).all()
    
    return [
        {
            "id": g.id,
            "ticket_id": g.ticket_id,
            "student_name": g.student_name,
            "student_email": g.student_email,
            "student_id": g.student_id,
            "title": g.title,
            "description": g.description,
            "category": g.category.value if g.category else "OTHER",
            "priority": g.priority.value if g.priority else "MEDIUM",
            "status": g.status.value if g.status else "SUBMITTED",
            "assigned_department": g.assigned_department,
            "ai_summary": g.ai_summary,
            "suggested_action": g.suggested_action,
            "created_at": g.created_at.isoformat() if g.created_at else None,
            "sla_deadline": g.sla_deadline.isoformat() if g.sla_deadline else None,
            "escalation_count": g.escalation_count,
        }
        for g in grievances
    ]


@app.get("/api/grievances/{ticket_id}")
def get_grievance(ticket_id: str, db: Session = Depends(get_db)):
    """Fetch detail and audit trail for a specific ticket."""
    grievance = db.query(Grievance).filter(Grievance.ticket_id == ticket_id).first()
    if not grievance:
        raise HTTPException(status_code=404, detail="Grievance ticket not found")
        
    logs = [
        {
            "action": log.action,
            "actor": log.actor,
            "details": log.details,
            "timestamp": log.timestamp.isoformat()
        }
        for log in grievance.logs
    ]

    return {
        "id": grievance.id,
        "ticket_id": grievance.ticket_id,
        "student_name": grievance.student_name,
        "student_email": grievance.student_email,
        "student_id": grievance.student_id,
        "title": grievance.title,
        "description": grievance.description,
        "category": grievance.category.value if grievance.category else "OTHER",
        "priority": grievance.priority.value if grievance.priority else "MEDIUM",
        "status": grievance.status.value if grievance.status else "SUBMITTED",
        "assigned_department": grievance.assigned_department,
        "sentiment_score": grievance.sentiment_score,
        "ai_summary": grievance.ai_summary,
        "suggested_action": grievance.suggested_action,
        "resolution_notes": grievance.resolution_notes,
        "created_at": grievance.created_at.isoformat() if grievance.created_at else None,
        "sla_deadline": grievance.sla_deadline.isoformat() if grievance.sla_deadline else None,
        "escalation_count": grievance.escalation_count,
        "logs": logs
    }


@app.post("/api/grievances/{ticket_id}/resolve")
def resolve_grievance(ticket_id: str, payload: dict, db: Session = Depends(get_db)):
    """Mark a grievance as resolved with official notes."""
    grievance = db.query(Grievance).filter(Grievance.ticket_id == ticket_id).first()
    if not grievance:
        raise HTTPException(status_code=404, detail="Grievance ticket not found")
        
    resolution_notes = payload.get("resolution_notes", "Resolved by department administrator.")
    grievance.status = GrievanceStatus.RESOLVED
    grievance.resolution_notes = resolution_notes

    log = GrievanceLog(
        grievance_id=grievance.id,
        action="GRIEVANCE_RESOLVED",
        actor=payload.get("resolved_by", "Department_Admin"),
        details=resolution_notes
    )
    db.add(log)
    db.commit()

    return {"success": True, "ticket_id": ticket_id, "status": GrievanceStatus.RESOLVED.value}


@app.post("/api/scheduler/check-escalations")
def trigger_escalation_check(db: Session = Depends(get_db)):
    """Manual or automated trigger for escalation checks."""
    check_and_escalate_grievances(db)
    return {"message": "Escalation check completed"}
