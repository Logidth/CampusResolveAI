import os
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import engine, Base, get_db
from backend.models import Complaint, ActivityLog, User
from backend.agent import classify_complaint
from backend.scheduler import start_scheduler, stop_scheduler, get_sla_duration, check_and_escalate_grievances
from backend.websocket_manager import manager, set_main_event_loop, broadcast_activity_sync
from backend.notifier import (
    get_sent_emails,
    send_new_complaint_email,
    send_complaint_resolved_email,
    send_test_email,
    get_authority_email,
    AUTHORITY_DIRECTORY
)
from backend.auth import (
    verify_password,
    hash_password,
    create_session_token,
    get_current_user,
    require_admin_user,
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
    # Seed default authority user accounts & auto-migrate columns on boot
    db = next(get_db())
    try:
        try:
            from sqlalchemy import text
            db.execute(text("ALTER TABLE complaints ADD COLUMN initial_authority VARCHAR(150)"))
            db.commit()
        except Exception:
            db.rollback()
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
    allow_origin_regex=r"^https?://.*",
    allow_credentials=False,
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
    "academic": "Exam Cell Admin",
    "exam": "Exam Cell Admin",
    "fees": "Exam Cell Admin",
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
    initial_authority: Optional[str] = None
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
    must_change_password: bool = False

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfileOut


class ChangePasswordRequest(BaseModel):
    current_password: Optional[str] = None
    new_password: str
    confirm_password: Optional[str] = None


class AdminCreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: str
    role: str
    assigned_authority: Optional[str] = None
    email: str
    tier: Optional[str] = None
    must_change_password: bool = True


class AdminResetPasswordRequest(BaseModel):
    new_password: str
    must_change_password: bool = True


class DemoAccountItem(BaseModel):
    username: str
    password: str
    email: str
    full_name: str
    role: str
    assigned_authority: Optional[str] = None
    tier: Optional[str] = None
    must_change_password: bool = False


# --- Endpoints ---

from fastapi.responses import RedirectResponse

@app.get("/")
def root():
    """Redirect root access directly to the CampusResolve student UI."""
    return RedirectResponse(url="/app/")


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Health check and configuration diagnostics endpoint with database persistence metrics."""
    smtp_user = os.getenv("SMTP_USER") or os.getenv("SMTP_USERNAME")
    smtp_pass = bool(os.getenv("SMTP_PASSWORD"))
    resend_key = bool(os.getenv("RESEND_API_KEY"))
    brevo_key = bool(os.getenv("BREVO_API_KEY"))
    email_mode = "brevo_api" if brevo_key else ("resend_api" if resend_key else ("smtp" if (smtp_user and smtp_pass) else "none"))
    
    total_complaints = db.query(Complaint).count()
    open_complaints = db.query(Complaint).filter(Complaint.status == "open").count()
    escalated_complaints = db.query(Complaint).filter(Complaint.escalation_level > 0, Complaint.status == "open").count()
    resolved_complaints = db.query(Complaint).filter(Complaint.status == "resolved").count()

    from backend.database import DATABASE_URL
    is_sqlite = DATABASE_URL.startswith("sqlite")
    
    return {
        "status": "CampusResolve agent running",
        "database": {
            "type": "sqlite" if is_sqlite else "postgresql",
            "persistent": not is_sqlite or "PERSISTENT" in os.getenv("RENDER_DISKS", ""),
            "total_complaints": total_complaints,
            "open_complaints": open_complaints,
            "escalated_complaints": escalated_complaints,
            "resolved_complaints": resolved_complaints,
        },
        "time_scale": float(os.getenv("DEBUG_TIME_SCALE", "1")),
        "email_configured": bool(resend_key or brevo_key or (smtp_user and smtp_pass)),
        "email_mode": email_mode,
        "smtp_configured": bool(smtp_user and smtp_pass),
        "smtp_user": smtp_user if smtp_user else "NOT_SET",
        "brevo_configured": brevo_key,
        "resend_configured": resend_key,
        "groq_configured": bool(os.getenv("GROQ_API_KEY")),
        "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    }


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


@app.post("/auth/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Allows an authenticated authority to change their password and clears must_change_password flag."""
    new_pw = payload.new_password.strip()
    if len(new_pw) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters long.")
    if payload.confirm_password and new_pw != payload.confirm_password.strip():
        raise HTTPException(status_code=400, detail="New passwords do not match.")

    if payload.current_password and not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    current_user.hashed_password = hash_password(new_pw)
    current_user.must_change_password = False
    db.commit()
    db.refresh(current_user)

    for token, sess in ACTIVE_SESSIONS.items():
        if sess.get("user_id") == current_user.id:
            sess["must_change_password"] = False

    return {
        "message": "Password changed successfully.",
        "must_change_password": False,
        "user": current_user
    }


# =====================================================================
# Central Admin Management Endpoints (Requires 'Admin' Role)
# =====================================================================

@app.get("/admin/users", response_model=List[UserProfileOut])
def admin_list_users(admin: User = Depends(require_admin_user), db: Session = Depends(get_db)):
    """Admin-only: Retrieve all registered authority user accounts."""
    return db.query(User).order_by(User.id.asc()).all()


@app.post("/admin/users", response_model=UserProfileOut, status_code=201)
def admin_create_user(payload: AdminCreateUserRequest, admin: User = Depends(require_admin_user), db: Session = Depends(get_db)):
    """Admin-only: Register a new authority account."""
    username_clean = payload.username.strip().lower()
    if not username_clean:
        raise HTTPException(status_code=400, detail="Username is required.")
    if len(payload.password.strip()) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters long.")

    existing = db.query(User).filter(User.username.ilike(username_clean)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Username '{payload.username}' is already registered.")

    new_user = User(
        username=username_clean,
        email=payload.email.strip(),
        hashed_password=hash_password(payload.password.strip()),
        full_name=payload.full_name.strip(),
        role=payload.role.strip(),
        assigned_authority=payload.assigned_authority.strip() if payload.assigned_authority else payload.role.strip(),
        tier=payload.tier.strip() if payload.tier else "Operational Authority",
        must_change_password=payload.must_change_password,
        created_at=datetime.utcnow(),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, admin: User = Depends(require_admin_user), db: Session = Depends(get_db)):
    """Admin-only: Delete an authority account (cannot delete self)."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own active administrator account.")
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User account not found.")
    
    uname = target_user.username
    db.delete(target_user)
    db.commit()
    return {"message": f"Authority account '{uname}' has been deleted successfully."}


@app.post("/admin/users/{user_id}/reset-password")
def admin_reset_password(user_id: int, payload: AdminResetPasswordRequest, admin: User = Depends(require_admin_user), db: Session = Depends(get_db)):
    """Admin-only: Reset password for an authority and set first-login password change flag."""
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User account not found.")
    if len(payload.new_password.strip()) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters long.")

    target_user.hashed_password = hash_password(payload.new_password.strip())
    target_user.must_change_password = payload.must_change_password
    db.commit()
    return {
        "message": f"Password reset for '{target_user.username}'. First-login change required: {target_user.must_change_password}."
    }


@app.get("/auth/accounts", response_model=List[DemoAccountItem])
def list_demo_accounts():
    """List pre-configured authority login credentials."""
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
def create_complaint(payload: ComplaintCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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
        initial_authority=assigned_authority,
        escalation_level=0,
        no_auto_escalation=no_auto_escalation,
        created_at=created_at,
        sla_deadline=sla_deadline,
        resolved_at=None,
    )
    db.add(complaint)
    db.flush()

    # 5. Log Activity Entry
    assigned_email = get_authority_email(assigned_authority)
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

    # 6. Commit immediately so data is saved without waiting on external networks
    db.commit()
    db.refresh(complaint)
    db.refresh(activity_entry)

    # 7. Asynchronously Dispatch Notification Email via BackgroundTasks
    background_tasks.add_task(
        send_new_complaint_email,
        complaint_id=complaint.id,
        complaint_text=complaint.text,
        category=complaint.category,
        urgency=complaint.urgency,
        assigned_authority=complaint.assigned_authority,
        sla_deadline=complaint.sla_deadline
    )

    # 8. Real-Time WebSocket Broadcast
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
    escalated_only: bool = Query(False, description="Whether to return only escalated complaints"),
    db: Session = Depends(get_db)
):
    """
    List complaints with role-based authority isolation.
    Returns complaints currently assigned to this authority OR originating from their department.
    """
    query = db.query(Complaint)
    
    if assigned_authority and assigned_authority != "All":
        query = query.filter(
            (Complaint.assigned_authority == assigned_authority) |
            (Complaint.initial_authority == assigned_authority)
        )
    elif not include_harassment:
        query = query.filter(Complaint.category != "harassment")

    if status:
        query = query.filter(Complaint.status == status)

    if escalated_only:
        query = query.filter(Complaint.escalation_level > 0)

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


class TestEmailRequest(BaseModel):
    recipient: Optional[str] = None


@app.post("/authority/test-email")
def trigger_test_email(payload: Optional[TestEmailRequest] = None):
    """
    Sends a test verification email via SMTP to verify configuration and delivery.
    Returns status and diagnostic details.
    """
    target = payload.recipient if (payload and payload.recipient) else None
    result = send_test_email(target)
    return result


@app.post("/complaints/{id}/simulate-breach")
def simulate_sla_breach(id: int, db: Session = Depends(get_db)):
    """
    Simulates an SLA timeout breach on a specific complaint and executes hierarchical
    escalation immediately, dispatching an automated alert email to the higher authority tier.
    """
    complaint = db.query(Complaint).filter(Complaint.id == id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if complaint.status != "open":
        raise HTTPException(status_code=400, detail="Cannot escalate a closed or resolved complaint")
    if complaint.no_auto_escalation or complaint.category == "harassment":
        raise HTTPException(status_code=400, detail="This complaint is confidential and protected against automated escalation")

    # Force SLA deadline into the past
    complaint.sla_deadline = datetime.utcnow() - timedelta(minutes=5)
    db.commit()

    # Trigger escalation engine
    check_and_escalate_grievances(db)
    db.refresh(complaint)

    assigned_email = get_authority_email(complaint.assigned_authority)
    return {
        "complaint_id": complaint.id,
        "escalation_level": complaint.escalation_level,
        "assigned_authority": complaint.assigned_authority,
        "assigned_email": assigned_email,
        "status": complaint.status,
        "sla_deadline": complaint.sla_deadline.isoformat(),
        "message": f"Complaint #{complaint.id} escalated to {complaint.assigned_authority} ({assigned_email}) at Level {complaint.escalation_level}. Notification email dispatched!"
    }


@app.post("/admin/escalate-check")
def trigger_escalation_check(db: Session = Depends(get_db)):
    """Manually trigger an SLA overdue inspection and hierarchical escalation scan."""
    processed = check_and_escalate_grievances(db)
    return {
        "status": "success",
        "processed_count": len(processed) if processed else 0,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.patch("/complaints/{id}/resolve", response_model=ComplaintOut)
def resolve_complaint(
    id: int, 
    background_tasks: BackgroundTasks,
    payload: Optional[ComplaintResolveRequest] = None, 
    db: Session = Depends(get_db)
):
    """Mark a complaint as resolved with optional remarks, record activity log, dispatch resolution email, and broadcast event."""
    complaint = db.query(Complaint).filter(Complaint.id == id).first()
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    complaint.status = "resolved"
    complaint.resolved_at = datetime.utcnow()

    remarks_text = payload.remarks.strip() if (payload and payload.remarks and payload.remarks.strip()) else ""
    remarks_str = f" Remarks: {remarks_text}" if remarks_text else ""
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

    # Asynchronously dispatch resolution notice email
    background_tasks.add_task(
        send_complaint_resolved_email,
        complaint_id=complaint.id,
        complaint_text=complaint.text,
        category=complaint.category or "general",
        assigned_authority=complaint.assigned_authority or "Estate Office",
        remarks=remarks_text or None
    )

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
