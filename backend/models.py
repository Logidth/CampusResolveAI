from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from backend.database import Base


class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    text = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)
    urgency = Column(String(50), nullable=True)
    status = Column(String(50), default="open", nullable=False)
    assigned_authority = Column(String(150), nullable=True)
    initial_authority = Column(String(150), nullable=True)
    ticket_id = Column(String(50), nullable=True, index=True)
    student_email = Column(String(150), nullable=True, index=True)
    student_name = Column(String(150), nullable=True)
    escalation_level = Column(Integer, default=0, nullable=False)
    no_auto_escalation = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    sla_deadline = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    # Relationship to ActivityLog
    activity_logs = relationship("ActivityLog", back_populates="complaint", cascade="all, delete-orphan")


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=False)
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationship to Complaint
    complaint = relationship("Complaint", back_populates="activity_logs")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(150), index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=False)
    role = Column(String(50), nullable=False)  # "Warden", "Dean of Student Affairs", "Admin", etc.
    assigned_authority = Column(String(150), nullable=True)  # Name of jurisdiction or None for Admin
    tier = Column(String(100), nullable=True)
    must_change_password = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

