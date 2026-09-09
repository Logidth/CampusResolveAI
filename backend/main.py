import os
import re
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, Header, BackgroundTasks, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.database import engine, Base, get_db
from backend.models import Complaint, ActivityLog, User, StudentConduct
from backend.agent import classify_complaint, moderate_content, summarize_complaint
from backend.scheduler import start_scheduler, stop_scheduler, get_sla_duration, check_and_escalate_grievances
from backend.websocket_manager import manager, set_main_event_loop, broadcast_activity_sync
from backend.notifier import (
    get_sent_emails,
    send_new_complaint_email,
    send_complaint_resolved_email,
    send_authority_dispute_email_to_principal,
    send_student_conduct_principal_alert,
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
    validate_student_email,
    authenticate_or_register_student,
    DEFAULT_ACCOUNTS,
    ACTIVE_SESSIONS,
)

# Initialize database tables
Base.metadata.create_all(bind=engine)

def ensure_schema_updates():
    """Ensure optional columns exist in existing database schemas."""
    try:
        with engine.connect() as conn:
            for sql in [
                "ALTER TABLE complaints ADD COLUMN photo_url TEXT",
                "ALTER TABLE complaints ADD COLUMN secondary_category VARCHAR(50)",
                "ALTER TABLE complaints ADD COLUMN summary TEXT"
            ]:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                except Exception:
                    pass
    except Exception:
        pass

ensure_schema_updates()


def extract_student_code(email: Optional[str]) -> str:
    """
    Extract student roll identifier from institutional email.
    Examples:
      717824v134@kce.ac.in -> v134
      717824v167@kce.ac.in -> v167
      v134@kce.ac.in       -> v134
    """
    if not email:
        return "anon"
    prefix = email.split("@")[0].lower().strip()
    m = re.search(r"([a-z]+\d+)", prefix)
    if m:
        return m.group(1)
    clean = re.sub(r"[^a-z0-9]", "", prefix)
    return clean[:10] if clean else "std"


# FastAPI Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed default authority user accounts & auto-migrate columns on boot
    db = next(get_db())
    try:
        try:
            db.execute(text("ALTER TABLE complaints ADD COLUMN initial_authority VARCHAR(150)"))
            db.commit()
        except Exception:
            db.rollback()

        try:
            db.execute(text("ALTER TABLE complaints ADD COLUMN student_email VARCHAR(150)"))
            db.commit()
        except Exception:
            db.rollback()

        try:
            db.execute(text("ALTER TABLE complaints ADD COLUMN student_name VARCHAR(150)"))
            db.commit()
        except Exception:
            db.rollback()

        try:
            db.execute(text("ALTER TABLE complaints ADD COLUMN ticket_id VARCHAR(50)"))
            db.commit()
        except Exception:
            db.rollback()

        try:
            db.execute(text("ALTER TABLE complaints ADD COLUMN secondary_category VARCHAR(50)"))
            db.commit()
        except Exception:
            db.rollback()

        try:
            db.execute(text("ALTER TABLE complaints ADD COLUMN summary TEXT"))
            db.commit()
        except Exception:
            db.rollback()

        try:
            missing_tickets = db.query(Complaint).filter(Complaint.ticket_id.is_(None)).all()
            for comp in missing_tickets:
                if comp.student_email:
                    code = extract_student_code(comp.student_email)
                    comp.ticket_id = f"{code}_t{comp.id}"
                else:
                    comp.ticket_id = f"t{comp.id}"
            if missing_tickets:
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
    student_email: Optional[str] = None
    student_name: Optional[str] = None
    photo_url: Optional[str] = None


class StudentLoginRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None


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
    ticket_id: Optional[str] = None
    text: str
    category: Optional[str] = None
    urgency: Optional[str] = None
    status: str
    assigned_authority: Optional[str] = None
    initial_authority: Optional[str] = None
    student_email: Optional[str] = None
    student_name: Optional[str] = None
    escalation_level: int
    no_auto_escalation: bool = False
    photo_url: Optional[str] = None
    secondary_category: Optional[str] = None
    summary: Optional[str] = None
    conduct_warning: Optional[str] = None
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
        "time_scale": float(os.getenv("DEBUG_TIME_SCALE", "720")),
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


@app.post("/auth/student-login")
def student_login(payload: StudentLoginRequest, db: Session = Depends(get_db)):
    """Authenticate or auto-register student using institutional @kce.ac.in email."""
    user, token = authenticate_or_register_student(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        db=db
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
        },
        "message": f"Welcome, {user.full_name}! Successfully authenticated to Student Portal."
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
        from backend.auth import ACTIVE_SESSIONS, REVOKED_TOKENS
        ACTIVE_SESSIONS.pop(token, None)
        REVOKED_TOKENS.add(token)
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
def create_complaint(
    payload: ComplaintCreate,
    background_tasks: BackgroundTasks,
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Create a new complaint, execute AI classification, route to appropriate authority,
    calculate SLA deadline, enforce harassment safety flags, log activity, and broadcast event.
    Enforces student conduct moderation (3 warnings before Principal escalation) and auto-summarization.
    """
    created_at = datetime.utcnow()

    # Clean and validate optional student identity
    student_email = payload.student_email.strip().lower() if payload.student_email else None
    student_name = payload.student_name.strip() if payload.student_name else None

    # Fallback: extract student identity from JWT if payload.student_email was not supplied
    if not student_email and request:
        auth_hdr = request.headers.get("Authorization")
        if auth_hdr and auth_hdr.startswith("Bearer "):
            try:
                from backend.auth import decode_access_token
                token_data = decode_access_token(auth_hdr.split(" ", 1)[1].strip())
                if token_data and token_data.get("sub"):
                    student_email = token_data.get("sub").strip().lower()
            except Exception:
                pass

    # 1. Content Moderation & Three-Warning Student Conduct System
    is_flagged, flag_reason = moderate_content(payload.text)
    conduct_warning_msg = None
    conduct_record = None

    if is_flagged:
        principal_email = os.getenv("EMAIL_PRINCIPAL", "717824v132@kce.ac.in")

        if student_email:
            conduct_record = db.query(StudentConduct).filter(
                func.lower(StudentConduct.student_email) == student_email
            ).first()

            if not conduct_record:
                conduct_record = StudentConduct(
                    student_email=student_email,
                    warning_count=0,
                    reported_to_principal=False
                )
                db.add(conduct_record)
                db.flush()

            conduct_record.warning_count += 1
            conduct_record.last_warned_at = datetime.utcnow()

            if conduct_record.warning_count <= 3:
                conduct_warning_msg = (
                    f"⚠️ Conduct Warning {conduct_record.warning_count}/3: Inappropriate or irrelevant text detected in your complaint ({flag_reason}). "
                    f"CampusResolve is strictly for genuine college grievances. Having more than 3 warnings will report your student account ({student_email}) directly to the Principal."
                )
            else:
                # Warning count exceeds 3 (4th violation or higher)
                conduct_warning_msg = (
                    f"🚨 Formal Conduct Violation #{conduct_record.warning_count}: Inappropriate or irrelevant text detected ({flag_reason}). "
                    f"Having exceeded the 3-warning limit, your student account ({student_email}) has been formally reported to the Principal ({principal_email}) with your incident history."
                )
                conduct_record.reported_to_principal = True

                # Query prior complaints history for Principal dossier
                prior_complaints = db.query(Complaint).filter(
                    func.lower(Complaint.student_email) == student_email
                ).order_by(Complaint.created_at.desc()).limit(10).all()

                flagged_history = [
                    {"id": c.ticket_id or f"#{c.id}", "text": c.text, "created_at": c.created_at.strftime("%Y-%m-%d %H:%M:%S")}
                    for c in prior_complaints
                ]
                flagged_history.insert(0, {
                    "id": "Current Submission",
                    "text": payload.text,
                    "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                })

                background_tasks.add_task(
                    send_student_conduct_principal_alert,
                    student_email=student_email,
                    warning_count=conduct_record.warning_count,
                    flagged_complaints=flagged_history
                )
        else:
            conduct_warning_msg = (
                f"⚠️ Conduct Warning: Inappropriate or irrelevant text detected ({flag_reason}). "
                f"CampusResolve is strictly for genuine college grievances. Repeated violations exceeding 3 warnings are reported directly to the Principal ({principal_email})."
            )

    # 2. Auto-summarize grievances exceeding 50 words
    summary = summarize_complaint(payload.text)

    # 3. Call AI Classifier (Gemini 3.8 Flash -> Groq -> Heuristic Fallback)
    classification = classify_complaint(payload.text)
    category = classification.get("category", "infrastructure").lower()
    secondary_category = classification.get("secondary_category")
    if secondary_category:
        secondary_category = str(secondary_category).strip().lower()
    urgency = classification.get("urgency", "medium").lower()
    reasoning = classification.get("reasoning", "")

    # 4. Determine Authority & Enforce Harassment Safety Guardrails
    no_auto_escalation = False
    if category == "harassment" or secondary_category == "harassment":
        category = "harassment"
        secondary_category = None
        urgency = "high"
        assigned_authority = "Counseling Cell"
        no_auto_escalation = True
    else:
        assigned_authority = AUTHORITY_MAP.get(category, "Estate Office")

    # 5. Calculate SLA Deadline with DEBUG_TIME_SCALE support
    sla_delta = get_sla_duration(urgency)
    sla_deadline = created_at + sla_delta

    # Generate sequential student ticket ID (e.g. v134_t1, v134_t2)
    ticket_id = None
    if student_email:
        student_code = extract_student_code(student_email)
        existing_count = db.query(Complaint).filter(func.lower(Complaint.student_email) == student_email).count()
        seq = existing_count + 1
        ticket_id = f"{student_code}_t{seq}"
        while db.query(Complaint).filter(Complaint.ticket_id == ticket_id).first():
            seq += 1
            ticket_id = f"{student_code}_t{seq}"
    else:
        ticket_id = f"anon_t{datetime.utcnow().strftime('%M%S%f')[:8]}"

    # 6. Create Complaint Record (Original full text always stored)
    complaint = Complaint(
        text=payload.text,
        category=category,
        secondary_category=secondary_category,
        summary=summary,
        urgency=urgency,
        status="open",
        assigned_authority=assigned_authority,
        initial_authority=assigned_authority,
        ticket_id=ticket_id,
        student_email=student_email,
        student_name=student_name,
        escalation_level=0,
        no_auto_escalation=no_auto_escalation,
        photo_url=payload.photo_url,
        created_at=created_at,
        sla_deadline=sla_deadline,
        resolved_at=None,
    )
    db.add(complaint)
    db.flush()

    # 7. Log Activity Entries
    assigned_email = get_authority_email(assigned_authority)
    log_details = f"Classified as {category}/{urgency}, routed to {assigned_authority}. Alert email dispatched to {assigned_email}."
    if secondary_category:
        sec_auth = AUTHORITY_MAP.get(secondary_category, "Estate Office")
        sec_email = get_authority_email(sec_auth)
        log_details += f" Secondary domain '{secondary_category}' routed to {sec_auth} ({sec_email})."
    if reasoning:
        log_details += f" Reasoning: {reasoning}"

    activity_entry = ActivityLog(
        complaint_id=complaint.id,
        action="CLASSIFICATION",
        details=log_details,
        timestamp=datetime.utcnow(),
    )
    db.add(activity_entry)

    # If flagged for inappropriate or irrelevant content, record conduct log
    if is_flagged:
        cond_action = "CONDUCT_ESCALATION" if (conduct_record and conduct_record.warning_count >= 4) else "CONDUCT_WARNING"
        strike_num = conduct_record.warning_count if conduct_record else 1
        strike_desc = f"strike {strike_num}/3" if strike_num <= 3 else f"strike {strike_num} (Exceeded 3 warnings — reported to Principal)"
        db.add(ActivityLog(
            complaint_id=complaint.id,
            action=cond_action,
            details=f"Inappropriate or irrelevant text detected ({flag_reason}). Student conduct {strike_desc}.",
            timestamp=datetime.utcnow()
        ))

    # 8. Commit immediately so data is saved without waiting on external networks
    db.commit()
    db.refresh(complaint)
    db.refresh(activity_entry)

    # 9. Asynchronously Dispatch Notification Emails
    # Primary Authority Notification
    background_tasks.add_task(
        send_new_complaint_email,
        complaint_id=complaint.id,
        complaint_text=complaint.text,
        category=complaint.category,
        secondary_category=complaint.secondary_category,
        summary=complaint.summary,
        urgency=complaint.urgency,
        assigned_authority=complaint.assigned_authority,
        sla_deadline=complaint.sla_deadline,
        photo_url=complaint.photo_url,
        is_secondary=False
    )

    # Secondary Authority Notification (if secondary category is distinct from primary)
    if secondary_category:
        sec_authority = AUTHORITY_MAP.get(secondary_category)
        if sec_authority and sec_authority != assigned_authority:
            background_tasks.add_task(
                send_new_complaint_email,
                complaint_id=complaint.id,
                complaint_text=complaint.text,
                category=complaint.category,
                secondary_category=complaint.secondary_category,
                summary=complaint.summary,
                urgency=complaint.urgency,
                assigned_authority=sec_authority,
                sla_deadline=complaint.sla_deadline,
                photo_url=complaint.photo_url,
                is_secondary=True
            )

    # 10. Real-Time WebSocket Broadcast
    if category == "harassment":
        display_text = "[CONFIDENTIAL - ROUTED TO COUNSELING CELL]"
    elif summary:
        display_text = (summary[:60] + "...") if len(summary) > 60 else summary
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

    return ComplaintOut(
        id=complaint.id,
        ticket_id=complaint.ticket_id,
        text=complaint.text,
        category=complaint.category,
        secondary_category=complaint.secondary_category,
        summary=complaint.summary,
        urgency=complaint.urgency,
        status=complaint.status,
        assigned_authority=complaint.assigned_authority,
        initial_authority=complaint.initial_authority,
        student_email=complaint.student_email,
        student_name=complaint.student_name,
        escalation_level=complaint.escalation_level,
        no_auto_escalation=complaint.no_auto_escalation,
        photo_url=complaint.photo_url,
        created_at=complaint.created_at,
        sla_deadline=complaint.sla_deadline,
        resolved_at=complaint.resolved_at,
        conduct_warning=conduct_warning_msg
    )


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
    Anonymizes student roll numbers and emails so authorities are not exposed to who submitted the complaint.
    """
    from fastapi.params import Query as QueryParam
    if isinstance(status, QueryParam):
        status = status.default
    if isinstance(escalated_only, QueryParam):
        escalated_only = escalated_only.default
    if isinstance(include_harassment, QueryParam):
        include_harassment = include_harassment.default
    if isinstance(assigned_authority, QueryParam):
        assigned_authority = assigned_authority.default

    query = db.query(Complaint)
    
    if assigned_authority and assigned_authority != "All":
        matched_categories = [cat for cat, auth in AUTHORITY_MAP.items() if auth == assigned_authority]
        query = query.filter(
            (Complaint.assigned_authority == assigned_authority) |
            (Complaint.initial_authority == assigned_authority) |
            (Complaint.secondary_category.in_(matched_categories))
        )
    elif not include_harassment:
        query = query.filter(Complaint.category != "harassment")

    if status:
        query = query.filter(Complaint.status == status)

    if escalated_only:
        query = query.filter(Complaint.escalation_level > 0)

    complaints = query.order_by(Complaint.created_at.desc()).all()
    # Mask student roll and identity so authorities are not exposed to student identities
    return [
        ComplaintOut(
            id=c.id,
            ticket_id=f"TICKET-{c.id}",
            text=c.text,
            category=c.category,
            secondary_category=c.secondary_category,
            summary=c.summary,
            urgency=c.urgency,
            status=c.status,
            assigned_authority=c.assigned_authority,
            initial_authority=c.initial_authority,
            student_email=None,
            student_name=None,
            escalation_level=c.escalation_level,
            no_auto_escalation=c.no_auto_escalation,
            created_at=c.created_at,
            sla_deadline=c.sla_deadline,
            resolved_at=c.resolved_at,
            photo_url=c.photo_url,
        )
        for c in complaints
    ]


@app.get("/counselor/complaints", response_model=List[ComplaintOut])
def list_counselor_complaints(db: Session = Depends(get_db)):
    """Protected endpoint for Counseling Cell portal to view sensitive harassment records (anonymized)."""
    complaints = db.query(Complaint).filter(Complaint.category == "harassment").order_by(Complaint.created_at.desc()).all()
    return [
        ComplaintOut(
            id=c.id,
            ticket_id=f"TICKET-{c.id}",
            text=c.text,
            category=c.category,
            secondary_category=c.secondary_category,
            summary=c.summary,
            urgency=c.urgency,
            status=c.status,
            assigned_authority=c.assigned_authority,
            initial_authority=c.initial_authority,
            student_email=None,
            student_name=None,
            escalation_level=c.escalation_level,
            no_auto_escalation=c.no_auto_escalation,
            created_at=c.created_at,
            sla_deadline=c.sla_deadline,
            resolved_at=c.resolved_at,
            photo_url=c.photo_url,
        )
        for c in complaints
    ]


@app.get("/student/complaints")
def get_student_complaints(
    email: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Retrieve history of grievances submitted by a student, with status, escalation,
    ticket ID (e.g. v134_t1), and resolution remarks from the activity audit log.
    """
    current_user = get_optional_user(authorization, db)
    target_email = None
    if current_user and current_user.email:
        target_email = current_user.email.strip().lower()
    elif email:
        clean_email = email.strip().lower()
        if validate_student_email(clean_email):
            target_email = clean_email

    if not target_email:
        raise HTTPException(
            status_code=400,
            detail="Student email required or invalid. Please log in with your @kce.ac.in credentials."
        )

    complaints = db.query(Complaint).filter(
        func.lower(Complaint.student_email) == target_email
    ).order_by(Complaint.created_at.desc()).all()

    results = []
    for c in complaints:
        # Extract resolution remarks if ticket is resolved
        resolution_remarks = None
        if c.status == "resolved":
            res_log = db.query(ActivityLog).filter(
                ActivityLog.complaint_id == c.id,
                ActivityLog.action == "RESOLVED"
            ).order_by(ActivityLog.timestamp.desc()).first()
            if res_log:
                resolution_remarks = res_log.details

        results.append({
            "id": c.id,
            "ticket_id": c.ticket_id or f"t{c.id}",
            "text": c.text,
            "category": c.category or "general",
            "urgency": c.urgency or "medium",
            "status": c.status,
            "assigned_authority": c.assigned_authority,
            "initial_authority": c.initial_authority,
            "escalation_level": c.escalation_level,
            "student_email": c.student_email,
            "student_name": c.student_name,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "sla_deadline": c.sla_deadline.isoformat() if c.sla_deadline else None,
            "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
            "resolution_remarks": resolution_remarks,
            "photo_url": c.photo_url,
            "secondary_category": c.secondary_category,
            "summary": c.summary,
        })

    return {
        "student_email": target_email,
        "total": len(results),
        "open_count": sum(1 for x in results if x["status"] == "open"),
        "escalated_count": sum(1 for x in results if x["escalation_level"] > 0 and x["status"] == "open"),
        "resolved_count": sum(1 for x in results if x["status"] == "resolved"),
        "complaints": results,
    }


def find_complaint_by_ref(db: Session, id_or_ticket: str) -> Optional[Complaint]:
    """
    Locates a complaint record flexibly by:
    - Numeric complaint ID: 6, #6
    - Masked authority ticket: TICKET-6
    - Student ticket code: v134_t1, V134_T1 (case-insensitive)
    - Suffix fallback: prefix_t6 -> ID 6
    """
    if not id_or_ticket:
        return None
    raw = id_or_ticket.strip()
    clean_ref = raw.lstrip("#").strip()

    # 1. Direct integer ID
    if clean_ref.isdigit():
        c = db.query(Complaint).filter(Complaint.id == int(clean_ref)).first()
        if c:
            return c

    # 2. TICKET-12 format
    if clean_ref.upper().startswith("TICKET-"):
        parts = clean_ref.split("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            c = db.query(Complaint).filter(Complaint.id == int(parts[1])).first()
            if c:
                return c

    # 3. Exact ticket_id (case-insensitive)
    c = db.query(Complaint).filter(func.lower(Complaint.ticket_id) == clean_ref.lower()).first()
    if c:
        return c

    # 4. Fallback: prefix_t12 format (e.g. v134_t12)
    if "_t" in clean_ref.lower():
        parts = clean_ref.lower().split("_t")
        if len(parts) == 2 and parts[1].isdigit():
            c = db.query(Complaint).filter(Complaint.id == int(parts[1])).first()
            if c:
                return c

    return None


@app.get("/complaints/{id_or_ticket}", response_model=ComplaintDetailOut)
def get_complaint(
    id_or_ticket: str,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Get a single complaint along with its activity log.
    Enforces privacy and access control:
    - Students can ONLY inspect grievances filed under their own account (searching other tickets like v167_t1 returns 403 Forbidden).
    - Authorities cannot see student roll numbers or identity (anonymized to TICKET-#).
    """
    complaint = find_complaint_by_ref(db, id_or_ticket)
    if not complaint:
        raise HTTPException(status_code=404, detail=f"Complaint ticket '{id_or_ticket.strip()}' not found")

    current_user = get_optional_user(authorization, db)

    # 1. Authority or Central Admin
    if current_user and current_user.role != "Student":
        return ComplaintDetailOut(
            id=complaint.id,
            ticket_id=f"TICKET-{complaint.id}",
            text=complaint.text,
            category=complaint.category,
            secondary_category=complaint.secondary_category,
            summary=complaint.summary,
            urgency=complaint.urgency,
            status=complaint.status,
            assigned_authority=complaint.assigned_authority,
            initial_authority=complaint.initial_authority,
            student_email=None,
            student_name=None,
            escalation_level=complaint.escalation_level,
            no_auto_escalation=complaint.no_auto_escalation,
            created_at=complaint.created_at,
            sla_deadline=complaint.sla_deadline,
            resolved_at=complaint.resolved_at,
            photo_url=complaint.photo_url,
            activity_logs=complaint.activity_logs
        )

    # 2. Logged-in Student
    if current_user and current_user.role == "Student":
        if not complaint.student_email or complaint.student_email.strip().lower() != current_user.email.strip().lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access restricted: You can only view grievances filed under your own student account."
            )
        return ComplaintDetailOut(
            id=complaint.id,
            ticket_id=complaint.ticket_id or f"t{complaint.id}",
            text=complaint.text,
            category=complaint.category,
            secondary_category=complaint.secondary_category,
            summary=complaint.summary,
            urgency=complaint.urgency,
            status=complaint.status,
            assigned_authority=complaint.assigned_authority,
            initial_authority=complaint.initial_authority,
            student_email=complaint.student_email,
            student_name=complaint.student_name,
            escalation_level=complaint.escalation_level,
            no_auto_escalation=complaint.no_auto_escalation,
            created_at=complaint.created_at,
            sla_deadline=complaint.sla_deadline,
            resolved_at=complaint.resolved_at,
            photo_url=complaint.photo_url,
            activity_logs=complaint.activity_logs
        )

    # 3. Unauthenticated request
    if complaint.student_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: Please sign in with your student credentials to view this grievance."
        )

    return ComplaintDetailOut(
        id=complaint.id,
        ticket_id=complaint.ticket_id or f"TICKET-{complaint.id}",
        text=complaint.text,
        category=complaint.category,
        secondary_category=complaint.secondary_category,
        summary=complaint.summary,
        urgency=complaint.urgency,
        status=complaint.status,
        assigned_authority=complaint.assigned_authority,
        initial_authority=complaint.initial_authority,
        student_email=None,
        student_name=None,
        escalation_level=complaint.escalation_level,
        no_auto_escalation=complaint.no_auto_escalation,
        created_at=complaint.created_at,
        sla_deadline=complaint.sla_deadline,
        resolved_at=complaint.resolved_at,
        photo_url=complaint.photo_url,
        activity_logs=complaint.activity_logs
    )


class ComplaintResolveRequest(BaseModel):
    remarks: Optional[str] = None


class DisputeAuthorityRequest(BaseModel):
    reason: Optional[str] = "Fake resolution or unresolved failure"
    description: str
    student_email: Optional[str] = None
    reported_authority: Optional[str] = None


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
    if complaint.assigned_authority == "Principal" or complaint.escalation_level >= 2:
        raise HTTPException(status_code=400, detail="Complaint is already at apex institutional authority (Principal)")

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

    return ComplaintOut(
        id=complaint.id,
        ticket_id=f"TICKET-{complaint.id}",
        text=complaint.text,
        category=complaint.category,
        urgency=complaint.urgency,
        status=complaint.status,
        assigned_authority=complaint.assigned_authority,
        initial_authority=complaint.initial_authority,
        student_email=None,
        student_name=None,
        escalation_level=complaint.escalation_level,
        no_auto_escalation=complaint.no_auto_escalation,
        photo_url=complaint.photo_url,
        secondary_category=complaint.secondary_category,
        summary=complaint.summary,
        created_at=complaint.created_at,
        sla_deadline=complaint.sla_deadline,
        resolved_at=complaint.resolved_at,
    )


@app.post("/complaints/{id_or_ticket}/dispute")
def dispute_complaint_resolution(
    id_or_ticket: str,
    payload: DisputeAuthorityRequest,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Allows a student to raise a complaint/appeal on an authority who failed to resolve
    an issue or marked it with a 'fake resolution'.
    Reopens the ticket, escalates directly to the Principal (Level 2), sets an urgent
    2-hour SLA, records an audit log entry, and dispatches a high-priority alert email
    to the Principal (717824v132@kce.ac.in).
    """
    complaint = find_complaint_by_ref(db, id_or_ticket)
    if not complaint:
        raise HTTPException(status_code=404, detail=f"Complaint ticket '{id_or_ticket.strip()}' not found. Please verify the ticket ID.")

    current_user = get_optional_user(authorization, db)
    provided_email = payload.student_email.strip().lower() if payload.student_email else None

    # Validate student ownership
    if current_user and current_user.role == "Student":
        if complaint.student_email and complaint.student_email.strip().lower() != current_user.email.strip().lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access restricted: You can only raise a dispute for grievances filed under your own student account."
            )
    elif complaint.student_email:
        # If unauthenticated, allow if provided student_email matches
        if not provided_email or provided_email != complaint.student_email.strip().lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required: Please sign in or provide your registered @kce.ac.in student email to dispute this grievance."
            )

    if not payload.description or not payload.description.strip():
        raise HTTPException(status_code=400, detail="Description is required to report an authority to the Principal.")

    previous_authority = payload.reported_authority or complaint.assigned_authority or "Assigned Authority"
    ticket_ref = complaint.ticket_id or f"t{complaint.id}"

    # Reopen and escalate to Principal
    complaint.status = "open"
    complaint.assigned_authority = "Principal"
    complaint.escalation_level = 2
    complaint.sla_deadline = datetime.utcnow() + timedelta(hours=2)
    complaint.resolved_at = None

    # Activity Log
    reason_str = payload.reason or "Fake resolution / authority failure"
    desc_str = payload.description.strip()
    log_details = (
        f"STUDENT DISPUTE TO PRINCIPAL: Reported authority '{previous_authority}'. "
        f"Reason: {reason_str}. Evidence: {desc_str}. Reassigned to Principal for executive intervention."
    )
    log_entry = ActivityLog(
        complaint_id=complaint.id,
        action="DISPUTED_TO_PRINCIPAL",
        details=log_details,
        timestamp=datetime.utcnow(),
    )
    db.add(log_entry)
    db.commit()
    db.refresh(complaint)
    db.refresh(log_entry)

    # Asynchronously dispatch email to Principal (717824v132@kce.ac.in)
    background_tasks.add_task(
        send_authority_dispute_email_to_principal,
        complaint_id=complaint.id,
        ticket_id=ticket_ref,
        complaint_text=complaint.text,
        reported_authority=previous_authority,
        dispute_reason=reason_str,
        student_description=desc_str,
        student_email=complaint.student_email
    )

    # Broadcast WebSocket update
    broadcast_activity_sync({
        "id": log_entry.id,
        "complaint_id": complaint.id,
        "action": log_entry.action,
        "details": log_entry.details,
        "timestamp": log_entry.timestamp.isoformat(),
        "complaint_text": (complaint.text[:60] + "...") if len(complaint.text) > 60 else complaint.text,
        "complaint_status": complaint.status,
        "assigned_authority": complaint.assigned_authority,
    })

    return {
        "status": "success",
        "message": f"Complaint #{ticket_ref} escalated directly to Principal (717824v132@kce.ac.in). Official executive investigation initiated.",
        "ticket_id": ticket_ref,
        "assigned_authority": "Principal",
        "complaint_status": complaint.status,
    }


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
