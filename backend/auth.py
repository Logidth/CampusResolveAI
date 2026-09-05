"""
CampusResolve Authentication & Authority Identity Management
Provides secure credential verification, session token issuance,
and auto-seeding of pre-configured university authority accounts.
"""

import os
import hashlib
import secrets
import logging
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
    """Create and register an active bearer session token."""
    token = "cr_token_" + secrets.token_urlsafe(32)
    ACTIVE_SESSIONS[token] = {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "assigned_authority": user.assigned_authority,
        "tier": user.tier,
        "expires_at": datetime.utcnow() + timedelta(days=7),
    }
    return token


def get_current_user_from_token(token: str, db: Session) -> Optional[User]:
    """Resolve User instance from session token."""
    if not token:
        return None
    
    # Strip 'Bearer ' if present
    if token.startswith("Bearer "):
        token = token[7:].strip()

    session_info = ACTIVE_SESSIONS.get(token)
    if not session_info:
        return None
    
    if datetime.utcnow() > session_info["expires_at"]:
        ACTIVE_SESSIONS.pop(token, None)
        return None
    
    return db.query(User).filter(User.id == session_info["user_id"]).first()


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


def get_optional_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """FastAPI dependency returning User if authenticated, else None."""
    if not authorization:
        return None
    return get_current_user_from_token(authorization, db)


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
        "tier": "Tier 1 — Operational (Hostels)"
    },
    {
        "username": "mess",
        "password": "mess123",
        "email": os.getenv("EMAIL_MESS", "dlogidth5@gmail.com"),
        "full_name": "Dr. Ananya Gupta (Mess Committee)",
        "role": "Mess Committee",
        "assigned_authority": "Mess Committee",
        "tier": "Tier 1 — Operational (Dining & Mess)"
    },
    {
        "username": "hod",
        "password": "hod123",
        "email": os.getenv("EMAIL_HOD", "717824v101@kce.ac.in"),
        "full_name": "Dr. Vikram Malhotra (HOD)",
        "role": "HOD",
        "assigned_authority": "HOD",
        "tier": "Tier 1 — Operational (Academics)"
    },
    {
        "username": "estate",
        "password": "estate123",
        "email": os.getenv("EMAIL_ESTATE", "717824v134@kce.ac.in"),
        "full_name": "Er. S. N. Roy (Estate Office)",
        "role": "Estate Office",
        "assigned_authority": "Estate Office",
        "tier": "Tier 1 — Operational (Infrastructure)"
    },
    {
        "username": "dean_student",
        "password": "dean123",
        "email": os.getenv("EMAIL_DEAN_STUDENT", "abijithmohanan2006@gmail.com"),
        "full_name": "Prof. Maya Verma (Dean Student Affairs)",
        "role": "Dean of Student Affairs",
        "assigned_authority": "Dean of Student Affairs",
        "tier": "Tier 2 — Executive (Hostel & Mess)"
    },
    {
        "username": "dean_academic",
        "password": "dean123",
        "email": os.getenv("EMAIL_DEAN_ACADEMIC", "717824v101@kce.ac.in"),
        "full_name": "Prof. Rajesh Iyer (Dean Academics)",
        "role": "Dean of Academics",
        "assigned_authority": "Dean of Academics",
        "tier": "Tier 2 — Executive (Academics)"
    },
    {
        "username": "vice_principal",
        "password": "vp123",
        "email": os.getenv("EMAIL_VICE_PRINCIPAL", "logidth78@gmail.com"),
        "full_name": "Prof. Arvind Swaminathan (Vice Principal)",
        "role": "Vice Principal",
        "assigned_authority": "Vice Principal",
        "tier": "Tier 2 — Executive (Infrastructure)"
    },
    {
        "username": "principal",
        "password": "principal123",
        "email": os.getenv("EMAIL_PRINCIPAL", "717824v27@kce.ac.in"),
        "full_name": "Dr. K. S. Pillai (Principal / Director)",
        "role": "Principal",
        "assigned_authority": "Principal",
        "tier": "Tier 3 — Apex Institutional Authority"
    },
    {
        "username": "counselor",
        "password": "counselor2026",
        "email": os.getenv("EMAIL_COUNSELOR", "717824v152@kce.ac.in"),
        "full_name": "Dr. Sunita Rao (Chief Counselor)",
        "role": "Counseling Cell",
        "assigned_authority": "Counseling Cell",
        "tier": "Protected — Student Safety & Wellness"
    },
    {
        "username": "admin",
        "password": "admin123",
        "email": os.getenv("EMAIL_ADMIN", "717824v134@kce.ac.in"),
        "full_name": "Central Institutional Administrator",
        "role": "Admin",
        "assigned_authority": "All",
        "tier": "Central Administration"
    }
]


def seed_authority_users(db: Session):
    """Seed default authority user accounts into SQLite database if not present."""
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
                created_at=datetime.utcnow(),
            )
            db.add(new_user)
            count_seeded += 1
        else:
            # Update password hash, email, and details
            existing.hashed_password = hash_password(acc["password"])
            existing.email = acc["email"]
            existing.full_name = acc["full_name"]
            existing.role = acc["role"]
            existing.assigned_authority = acc["assigned_authority"]
            existing.tier = acc["tier"]
            
    db.commit()
    if count_seeded > 0:
        logger.info(f"Seeded {count_seeded} default authority accounts into database.")
