"""
CampusResolve Escalation & SLA Scheduler
Periodically checks for overdue tickets and triggers automated agent escalations.
"""

from datetime import datetime
import logging
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.models import Grievance, GrievanceStatus, GrievanceLog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CampusResolveScheduler")


def check_and_escalate_grievances(db: Session = None):
    """Scan open grievances for breached SLAs and automatically escalate them."""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        now = datetime.utcnow()
        overdue_grievances = db.query(Grievance).filter(
            Grievance.status.in_([GrievanceStatus.SUBMITTED, GrievanceStatus.ASSIGNED, GrievanceStatus.IN_PROGRESS]),
            Grievance.sla_deadline.isnot(None),
            Grievance.sla_deadline < now
        ).all()

        for g in overdue_grievances:
            g.status = GrievanceStatus.ESCALATED
            g.escalation_count += 1
            
            log = GrievanceLog(
                grievance_id=g.id,
                action="AUTOMATIC_ESCALATION",
                actor="Agent_SLAScheduler",
                details=f"SLA deadline ({g.sla_deadline}) breached. Escalated to higher authority level {g.escalation_count}."
            )
            db.add(log)
            logger.warning(f"Ticket {g.ticket_id} escalated due to SLA breach.")

        if overdue_grievances:
            db.commit()
            logger.info(f"Escalated {len(overdue_grievances)} overdue grievances.")
    except Exception as e:
        logger.error(f"Error during SLA escalation check: {e}")
        db.rollback()
    finally:
        if close_db:
            db.close()


def start_scheduler():
    """Optional background scheduler runner using APScheduler if initialized."""
    logger.info("CampusResolve background scheduler initialized.")
