"""
CampusResolve Escalation & SLA Scheduler
Periodically checks for overdue complaints and triggers automated agent escalations.
Excludes complaints flagged with no_auto_escalation (e.g. harassment complaints).
"""

from datetime import datetime
import logging
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.models import Complaint, ActivityLog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CampusResolveScheduler")


def check_and_escalate_grievances(db: Session = None):
    """Scan open complaints for breached SLAs and automatically escalate them."""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        now = datetime.utcnow()
        overdue_complaints = db.query(Complaint).filter(
            Complaint.status == "open",
            Complaint.no_auto_escalation == False,
            Complaint.category != "harassment",
            Complaint.sla_deadline.isnot(None),
            Complaint.sla_deadline < now
        ).all()

        for c in overdue_complaints:
            c.escalation_level += 1
            
            log = ActivityLog(
                complaint_id=c.id,
                action="AUTOMATIC_ESCALATION",
                details=f"SLA deadline breached. Escalation level increased to {c.escalation_level}."
            )
            db.add(log)
            logger.warning(f"Complaint ID {c.id} escalated due to SLA breach.")

        if overdue_complaints:
            db.commit()
            logger.info(f"Escalated {len(overdue_complaints)} overdue complaints.")
    except Exception as e:
        logger.error(f"Error during SLA escalation check: {e}")
        db.rollback()
    finally:
        if close_db:
            db.close()
