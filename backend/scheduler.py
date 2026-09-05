"""
CampusResolve Escalation & SLA Scheduler
Uses APScheduler to periodically inspect open complaints and execute automated hierarchical escalations.
"""

import os
from datetime import datetime, timedelta
import logging
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from backend.database import SessionLocal
from backend.models import Complaint, ActivityLog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CampusResolveScheduler")

# Tiered Escalation Hierarchy
ESCALATION_TIERS = {
    "Warden": "Dean of Student Affairs",
    "Mess Committee": "Dean of Student Affairs",
    "HOD": "Dean of Academics",
    "Estate Office": "Vice Principal",
    "Dean of Student Affairs": "Principal",
    "Dean of Academics": "Principal",
    "Vice Principal": "Principal",
    "Principal": "Principal",
}

NOMINAL_SLA_HOURS = {
    "high": 6,
    "medium": 48,
    "low": 168,
}


def get_sla_duration(urgency: str) -> timedelta:
    """
    Calculate SLA duration considering the DEBUG_TIME_SCALE environment variable.
    If DEBUG_TIME_SCALE=3600, 1 real second = 1 simulated hour.
    """
    try:
        scale = float(os.getenv("DEBUG_TIME_SCALE", "1"))
        if scale <= 0:
            scale = 1.0
    except ValueError:
        scale = 1.0

    nominal_hours = NOMINAL_SLA_HOURS.get(urgency.lower() if urgency else "medium", 48)
    total_seconds = (nominal_hours * 3600.0) / scale
    return timedelta(seconds=total_seconds)


def get_next_authority(current_authority: str) -> str:
    """Determine the next authority tier in the university escalation tree."""
    if not current_authority:
        return "Dean of Student Affairs"
    
    if current_authority in ESCALATION_TIERS:
        return ESCALATION_TIERS[current_authority]
    
    # Heuristic fallback for custom or intermediate authority labels
    if "Dean" in current_authority or "Vice Principal" in current_authority:
        return "Principal"
    return "Principal"


def check_and_escalate_grievances(db: Session = None):
    """
    Background job:
    1. Finds all complaints where status="open" AND sla_deadline has passed AND no_auto_escalation is not true
    2. For each, increment escalation_level by 1
    3. Reassign assigned_authority to the next tier
    4. Extend sla_deadline by the original duration
    5. Log activity_log entry: 'Escalated from {old_authority} to {new_authority} — no resolution within SLA'
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        now = datetime.utcnow()
        overdue_complaints = db.query(Complaint).filter(
            Complaint.status == "open",
            Complaint.no_auto_escalation.is_(False),
            Complaint.sla_deadline.isnot(None),
            Complaint.sla_deadline < now
        ).all()

        for c in overdue_complaints:
            old_authority = c.assigned_authority or "Unassigned"
            new_authority = get_next_authority(old_authority)
            
            # 1. Increment escalation level
            c.escalation_level += 1
            
            # 2. Reassign to next tier
            c.assigned_authority = new_authority
            
            # 3. Extend SLA deadline by the original duration
            extension_delta = get_sla_duration(c.urgency)
            c.sla_deadline = now + extension_delta
            
            # 4. Log activity_log entry
            log_entry = ActivityLog(
                complaint_id=c.id,
                action="ESCALATED",
                details=f"Escalated from {old_authority} to {new_authority} — no resolution within SLA",
                timestamp=now
            )
            db.add(log_entry)
            logger.info(
                f"[ESCALATION] Complaint #{c.id} escalated: Level {c.escalation_level}, "
                f"routed from '{old_authority}' to '{new_authority}', new SLA: {c.sla_deadline.isoformat()}"
            )

        if overdue_complaints:
            db.commit()
            logger.info(f"Successfully processed {len(overdue_complaints)} escalated complaints.")
    except Exception as e:
        logger.error(f"Error during SLA escalation check: {e}")
        db.rollback()
    finally:
        if close_db:
            db.close()


# Background scheduler instance
scheduler = BackgroundScheduler()


def start_scheduler():
    """Start APScheduler background job running every 10 seconds."""
    if not scheduler.running:
        scheduler.add_job(
            check_and_escalate_grievances,
            trigger="interval",
            seconds=10,
            id="sla_escalation_job",
            replace_existing=True
        )
        scheduler.start()
        logger.info("APScheduler started: scanning for overdue complaints every 10 seconds.")


def stop_scheduler():
    """Gracefully shutdown the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
