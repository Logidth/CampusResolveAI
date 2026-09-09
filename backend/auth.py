"""
CampusResolve Authentication & Authority Identity Management
Provides secure credential verification, session token issuance,
and auto-seeding of pre-configured university authority accounts.
"""

import os
import hashlib
import secrets
import logging
import base64
import json
import hmac
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from fastapi import Depends, HTTPException, Header, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User

logger = logging.getLogger("CampusResolveAuth")

AUTH_SECRET_SALT = os.getenv("AUTH_SECRET_SALT", "campus-resolve-secure-salt-2026")

# In-memory active session tokens store: { token: { user_id, username, role, assigned_authority, tier, expires_at } }
ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
REVOKED_TOKENS: set = set()


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with salt."""
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        AUTH_SECRET_SALT.encode("utf-8"),
        100000
    )
    return key.hex()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against stored hash."""
    return hash_password(plain_password) == hashed_password


def create_session_token(user: User) -> str:
    """Create and register an active HMAC-signed bearer session token."""
    exp = int((datetime.utcnow() + timedelta(days=14)).timestamp())
    payload = {
        "uid": user.id,
        "usr": user.username,
        "rol": user.role,
        "exp": exp,
        "rnd": secrets.token_hex(4)
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET_SALT.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:32]
    token = f"cr_token_{payload_b64}.{sig}"

    ACTIVE_SESSIONS[token] = {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "assigned_authority": user.assigned_authority,
        "tier": user.tier,
        "must_change_password": bool(getattr(user, "must_change_password", False)),
        "expires_at": datetime.utcnow() + timedelta(days=14),
    }
    return token


def get_current_user_from_token(token: str, db: Session) -> Optional[User]:
    """Resolve User instance from session token (supports both in-memory cache and signed tokens)."""
    if not token:
        return None
    
    # Strip 'Bearer ' if present
    if token.startswith("Bearer "):
        token = token[7:].strip()

    if token in REVOKED_TOKENS:
        return None

    # 1. Fast path: check in-memory active sessions
    session_info = ACTIVE_SESSIONS.get(token)
    if session_info:
        if datetime.utcnow() > session_info["expires_at"]:
            ACTIVE_SESSIONS.pop(token, None)
            return None
        return db.query(User).filter(User.id == session_info["user_id"]).first()

    # 2. Resilient path: verify cryptographically signed token (survives container restarts / redeploys)
    if token.startswith("cr_token_") and "." in token:
        try:
            rest = token[9:]
            payload_b64, sig = rest.split(".", 1)
            expected_sig = hmac.new(AUTH_SECRET_SALT.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:32]
            if not hmac.compare_digest(sig, expected_sig):
                return None
            
            padded = payload_b64 + "=" * (-len(payload_b64) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
            
            if datetime.utcnow().timestamp() > data.get("exp", 0):
                return None
            
            user = db.query(User).filter(User.id == data.get("uid")).first()
            if user:
                # Re-cache into active sessions
                ACTIVE_SESSIONS[token] = {
                    "user_id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": user.role,
                    "assigned_authority": user.assigned_authority,
                    "tier": user.tier,
                    "must_change_password": bool(getattr(user, "must_change_password", False)),
                    "expires_at": datetime.utcfromtimestamp(data.get("exp", 0)),
                }
                return user
        except Exception as e:
            logger.debug(f"Failed to decode signed token: {e}")
            return None

    return None


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> User:
    """FastAPI dependency for protected routes requiring valid authentication."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = get_current_user_from_token(authorization, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency strictly restricting access to Central Admin."""
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Central Administrator privileges required."
        )
    return current_user


def require_principal_user(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency strictly restricting access to Principal."""
    if current_user.role != "Principal":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Principal privileges required."
        )
    return current_user


def get_optional_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """FastAPI dependency returning User if authenticated, else None."""
    if not authorization:
        return None
    return get_current_user_from_token(authorization, db)


def validate_student_email(email: str) -> bool:
    """Validate that the provided email belongs to the institutional @kce.ac.in domain."""
    if not email or not isinstance(email, str):
        return False
    clean_email = email.strip().lower()
    return clean_email.endswith("@kce.ac.in") and "@" in clean_email and len(clean_email.split("@")[0]) > 0


def authenticate_or_register_student(
    email: str,
    password: str,
    full_name: Optional[str] = None,
    db: Session = None
) -> tuple[User, str]:
    """
    Authenticate an existing student or auto-register a first-time student with an @kce.ac.in email.
    Returns (User, session_token).
    """
    clean_email = (email or "").strip().lower()
    if not validate_student_email(clean_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access restricted: Only official college institutional email addresses ending with @kce.ac.in are allowed."
        )

    if not password or len(password.strip()) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 4 characters."
        )

    # Check for existing student account by email and role
    user = db.query(User).filter(User.email == clean_email, User.role == "Student").first()
    if user:
        # Existing student account: verify password
        if not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password for this student account. Please try again."
            )
    else:
        # First-time student registration
        prefix = clean_email.split("@")[0]
        base_username = f"std_{prefix}"
        existing_username = db.query(User).filter(User.username == base_username).first()
        if existing_username:
            base_username = f"std_{prefix}_{secrets.token_hex(2)}"

        display_name = full_name.strip() if (full_name and full_name.strip()) else prefix.upper()
        user = User(
            username=base_username,
            email=clean_email,
            hashed_password=hash_password(password),
            full_name=display_name,
            role="Student",
            assigned_authority=None,
            tier="Student",
            must_change_password=False,
            created_at=datetime.utcnow()
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_session_token(user)
    return user, token


# =====================================================================
# Authority Accounts Matrix & Database Seeder
# =====================================================================

DEFAULT_ACCOUNTS = [
    {
        "username": "warden",
        "password": "warden123",
        "email": os.getenv("EMAIL_WARDEN", "dlogidth4@gmail.com"),
        "full_name": "Prof. R. K. Sharma (Warden)",
        "role": "Warden",
        "assigned_authority": "Warden",
        "tier": "Tier 1 — Operational (Hostels)",
        "must_change_password": False
    },
    {
        "username": "mess",
        "password": "mess123",
        "email": os.getenv("EMAIL_MESS", "dlogidth5@gmail.com"),
        "full_name": "Dr. Ananya Gupta (Mess Committee)",
        "role": "Mess Committee",
        "assigned_authority": "Mess Committee",
        "tier": "Tier 1 — Operational (Dining & Mess)",
        "must_change_password": False
    },
    {
        "username": "exam_cell",
        "password": "examcell123",
        "email": os.getenv("EMAIL_EXAM_CELL", "717824v101@kce.ac.in"),
        "full_name": "Controller of Examinations (Exam Cell Admin)",
        "role": "Exam Cell Admin",
        "assigned_authority": "Exam Cell Admin",
        "tier": "Tier 1 — Operational (Marks, Semester & Fees)",
        "must_change_password": False
    },
    {
        "username": "estate",
        "password": "estate123",
        "email": os.getenv("EMAIL_ESTATE", "717824v134@kce.ac.in"),
        "full_name": "Er. S. N. Roy (Estate Office)",
        "role": "Estate Office",
        "assigned_authority": "Estate Office",
        "tier": "Tier 1 — Operational (Infrastructure)",
        "must_change_password": False
    },
    {
        "username": "dean_student",
        "password": "dean123",
        "email": os.getenv("EMAIL_DEAN_STUDENT", "abijithmohanan2006@gmail.com"),
        "full_name": "Prof. Maya Verma (Dean Student Affairs)",
        "role": "Dean of Student Affairs",
        "assigned_authority": "Dean of Student Affairs",
        "tier": "Tier 2 — Executive (Hostel & Mess)",
        "must_change_password": False
    },
    {
        "username": "dean_academic",
        "password": "dean123",
        "email": os.getenv("EMAIL_DEAN_ACADEMIC", "717824v101@kce.ac.in"),
        "full_name": "Prof. Rajesh Iyer (Dean Academics)",
        "role": "Dean of Academics",
        "assigned_authority": "Dean of Academics",
        "tier": "Tier 2 — Executive (Academics)",
        "must_change_password": False
    },
    {
        "username": "vice_principal",
        "password": "vp123",
        "email": os.getenv("EMAIL_VICE_PRINCIPAL", "logidth78@gmail.com"),
        "full_name": "Prof. Arvind Swaminathan (Vice Principal)",
        "role": "Vice Principal",
        "assigned_authority": "Vice Principal",
        "tier": "Tier 2 — Executive (Infrastructure)",
        "must_change_password": False
    },
    {
        "username": "principal",
        "password": "principal123",
        "email": os.getenv("EMAIL_PRINCIPAL", "717824v132@kce.ac.in"),
        "full_name": "Dr. K. S. Pillai (Principal / Director)",
        "role": "Principal",
        "assigned_authority": "Principal",
        "tier": "Tier 3 — Apex Institutional Authority",
        "must_change_password": False
    },
    {
        "username": "counselor",
        "password": "counselor2026",
        "email": os.getenv("EMAIL_COUNSELOR", "717824v152@kce.ac.in"),
        "full_name": "Dr. Sunita Rao (Chief Counselor)",
        "role": "Counseling Cell",
        "assigned_authority": "Counseling Cell",
        "tier": "Protected — Student Safety & Wellness",
        "must_change_password": False
    },
    {
        "username": "logi",
        "password": "admin@1",
        "email": os.getenv("EMAIL_ADMIN", "717824v134@kce.ac.in"),
        "full_name": "Logi (Central Institutional Administrator)",
        "role": "Admin",
        "assigned_authority": "All",
        "tier": "Central Administration",
        "must_change_password": False
    }
]


def seed_authority_users(db: Session):
    """Seed default authority user accounts into SQLite database if not present."""
    # 1. Ensure must_change_password column exists (SQLite auto-migration)
    try:
        from sqlalchemy import text
        db.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 0"))
        db.commit()
    except Exception:
        db.rollback()

    # 2. Migrate legacy 'admin' to 'logi' if 'logi' does not exist yet
    legacy_admin = db.query(User).filter(User.username == "admin").first()
    logi_exists = db.query(User).filter(User.username == "logi").first()
    if legacy_admin and not logi_exists:
        legacy_admin.username = "logi"
        legacy_admin.full_name = "Logi (Central Institutional Administrator)"
        legacy_admin.role = "Admin"
        legacy_admin.assigned_authority = "All"
        legacy_admin.tier = "Central Administration"
        db.commit()
    elif legacy_admin and logi_exists:
        db.delete(legacy_admin)
        db.commit()

    # 3. Migrate legacy 'hod' to 'exam_cell' if 'exam_cell' does not exist yet
    legacy_hod = db.query(User).filter(User.username == "hod").first()
    exam_cell_exists = db.query(User).filter(User.username == "exam_cell").first()
    if legacy_hod and not exam_cell_exists:
        legacy_hod.username = "exam_cell"
        legacy_hod.full_name = "Controller of Examinations (Exam Cell Admin)"
        legacy_hod.role = "Exam Cell Admin"
        legacy_hod.assigned_authority = "Exam Cell Admin"
        legacy_hod.tier = "Tier 1 — Operational (Marks, Semester & Fees)"
        legacy_hod.email = os.getenv("EMAIL_EXAM_CELL", "717824v101@kce.ac.in")
        db.commit()
    elif legacy_hod and exam_cell_exists:
        db.delete(legacy_hod)
        db.commit()

    count_seeded = 0
    for acc in DEFAULT_ACCOUNTS:
        existing = db.query(User).filter(User.username == acc["username"]).first()
        
        if not existing:
            new_user = User(
                username=acc["username"],
                email=acc["email"],
                hashed_password=hash_password(acc["password"]),
                full_name=acc["full_name"],
                role=acc["role"],
                assigned_authority=acc["assigned_authority"],
                tier=acc["tier"],
                must_change_password=acc.get("must_change_password", False),
                created_at=datetime.utcnow(),
            )
            db.add(new_user)
            count_seeded += 1
        else:
            # Refresh metadata only for default accounts - NEVER overwrite existing passwords!
            existing.email = acc["email"]
            existing.full_name = acc["full_name"]
            existing.role = acc["role"]
            existing.assigned_authority = acc["assigned_authority"]
            existing.tier = acc["tier"]
            
    db.commit()
    if count_seeded > 0:
        logger.info(f"Seeded {count_seeded} default authority accounts into database.")
