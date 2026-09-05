"""
CampusResolve Escalation & SLA Scheduler
Uses APScheduler to periodically inspect open complaints, execute automated hierarchical escalations,
dispatch notification emails to escalated authorities, and broadcast real-time events via WebSocket.
"""

import os
from datetime import datetime, timedelta
import logging
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from backend.database import SessionLocal
from backend.models import Complaint, ActivityLog
from backend.websocket_manager import broadcast_activity_sync
from backend.notifier import send_escalation_email, get_authority_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CampusResolveScheduler")

# Tiered Escalation Hierarchy
# Warden ➔ Dean of Student Affairs ➔ Principal
# Mess Committee ➔ Dean of Student Affairs ➔ Principal
# HOD ➔ Dean of Academics ➔ Principal
# Estate Office ➔ Vice Principal ➔ Principal
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
    
    if "Dean" in current_authority or "Vice Principal" in current_authority:
        return "Principal"
    return "Principal"


def check_and_escalate_grievances(db: Session = None):
    """
    Background job:
    1. Finds all complaints where status="open" AND sla_deadline has passed AND no_auto_escalation is not true
    2. For each, increment escalation_level by 1
    3. Reassign assigned_authority to the next tier:
       Warden ➔ Dean of Student Affairs ➔ Principal
       Mess Committee ➔ Dean of Student Affairs ➔ Principal
       HOD ➔ Dean of Academics ➔ Principal
       Estate Office ➔ Vice Principal ➔ Principal
    4. Extend sla_deadline by the original duration
    5. Send escalation email alert to newly assigned authority
    6. Log activity_log entry
    7. Broadcast real-time WebSocket event
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
            Complaint.category != "harassment",
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
            
            # 4. Dispatch automated escalation email
            new_authority_email = get_authority_email(new_authority)
            send_escalation_email(
                complaint_id=c.id,
                complaint_text=c.text,
                category=c.category or "general",
                urgency=c.urgency or "medium",
                old_authority=old_authority,
                new_authority=new_authority,
                escalation_level=c.escalation_level,
                new_sla=c.sla_deadline
            )

            # 5. Log activity_log entry
            log_details = f"Escalated from {old_authority} to {new_authority} — no resolution within SLA. Alert email dispatched to {new_authority_email}."
            log_entry = ActivityLog(
                complaint_id=c.id,
                action="ESCALATED",
                details=log_details,
                timestamp=now
            )
            db.add(log_entry)
            db.flush()

            # 6. Broadcast real-time event via WebSocket
            truncated_text = (c.text[:60] + "...") if len(c.text) > 60 else c.text
            broadcast_activity_sync({
                "id": log_entry.id,
                "complaint_id": c.id,
                "action": "ESCALATED",
                "details": log_details,
                "timestamp": now.isoformat(),
                "complaint_text": truncated_text,
                "complaint_status": c.status,
                "assigned_authority": new_authority,
            })

            logger.info(
                f"[ESCALATION] Complaint #{c.id} escalated: Level {c.escalation_level}, "
                f"routed from '{old_authority}' to '{new_authority}' ({new_authority_email}), new SLA: {c.sla_deadline.isoformat()}"
            )

        if overdue_complaints:
            db.commit()
            logger.info(f"Successfully processed {len(overdue_complaints)} escalated complaints with email notifications.")
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
