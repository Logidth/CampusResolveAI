from datetime import datetime
from enum import Enum
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import relationship
from backend.database import Base


class GrievanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ANALYZING = "ANALYZING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class PriorityLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class GrievanceCategory(str, Enum):
    ACADEMIC = "ACADEMIC"
    HOSTEL = "HOSTEL"
    MAINTENANCE = "MAINTENANCE"
    FINANCIAL = "FINANCIAL"
    FACULTY = "FACULTY"
    HARASSMENT = "HARASSMENT"
    TRANSPORT = "TRANSPORT"
    OTHER = "OTHER"


class Grievance(Base):
    __tablename__ = "grievances"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String(32), unique=True, index=True, nullable=False)
    student_name = Column(String(100), nullable=False)
    student_email = Column(String(120), nullable=False)
    student_id = Column(String(50), nullable=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    
    # Agent classified fields
    category = Column(SQLEnum(GrievanceCategory), default=GrievanceCategory.OTHER)
    priority = Column(SQLEnum(PriorityLevel), default=PriorityLevel.MEDIUM)
    status = Column(SQLEnum(GrievanceStatus), default=GrievanceStatus.SUBMITTED)
    assigned_department = Column(String(100), nullable=True)
    sentiment_score = Column(String(50), nullable=True)
    ai_summary = Column(Text, nullable=True)
    suggested_action = Column(Text, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    # Timestamps & SLAs
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sla_deadline = Column(DateTime, nullable=True)
    escalation_count = Column(Integer, default=0)

    logs = relationship("GrievanceLog", back_populates="grievance", cascade="all, delete-orphan")


class GrievanceLog(Base):
    __tablename__ = "grievance_logs"

    id = Column(Integer, primary_key=True, index=True)
    grievance_id = Column(Integer, ForeignKey("grievances.id"), nullable=False)
    action = Column(String(100), nullable=False)
    actor = Column(String(100), default="Agentic_AI")
    details = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    grievance = relationship("Grievance", back_populates="logs")
