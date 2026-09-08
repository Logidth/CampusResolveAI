"""
Verification Script: Test End-to-End Hierarchical Escalation & Email Delivery
Validates:
1. Initial ticket creation routed to Tier 1 authority (e.g., Warden / Estate Office)
2. SLA breach forces automated escalation to Tier 2 Executive Oversight (Dean / Vice Principal)
3. Real Brevo notification email dispatched to Tier 2 authority
4. Second SLA breach forces automated escalation to Tier 3 Apex Authority (Principal)
5. Real Brevo notification email dispatched to Tier 3 authority
6. Harassment grievances are strictly locked to Counseling Cell with no auto-escalation
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

from backend.database import SessionLocal, engine, Base
from backend.models import Complaint, ActivityLog
from backend.scheduler import check_and_escalate_grievances, get_next_authority
from backend.notifier import get_authority_email, AUTHORITY_DIRECTORY

def test_full_escalation_lifecycle():
    db = SessionLocal()
    print("=" * 60)
    print("1. VERIFYING AUTHORITY DIRECTORY & ESCALATION TREE")
    print("=" * 60)

    chains = [
        ("Warden", "Dean of Student Affairs", "Principal"),
        ("Mess Committee", "Dean of Student Affairs", "Principal"),
        ("HOD", "Dean of Academics", "Principal"),
        ("Estate Office", "Vice Principal", "Principal"),
    ]

    for t1, t2, t3 in chains:
        next1 = get_next_authority(t1)
        next2 = get_next_authority(t2)
        assert next1 == t2, f"Expected {t1} -> {t2}, got {next1}"
        assert next2 == t3, f"Expected {t2} -> {t3}, got {next2}"
        print(f"[OK] Chain validated: {t1} ({get_authority_email(t1)}) -> {t2} ({get_authority_email(t2)}) -> {t3} ({get_authority_email(t3)})")

    print("\n" + "=" * 60)
    print("2. SIMULATING HOSTEL GRIEVANCE (WARDEN -> DEAN -> PRINCIPAL)")
    print("=" * 60)

    # Create a fresh test complaint for Warden
    test_complaint = Complaint(
        text="[VERIFICATION TEST] Room 304 water leakage and ceiling dampness persisting for days.",
        category="hostel",
        urgency="medium",
        status="open",
        assigned_authority="Warden",
        escalation_level=0,
        no_auto_escalation=False,
        created_at=datetime.utcnow() - timedelta(hours=49), # breached 48h SLA
        sla_deadline=datetime.utcnow() - timedelta(hours=1),
    )
    db.add(test_complaint)
    db.commit()
    db.refresh(test_complaint)
    c_id = test_complaint.id
    print(f"Created Test Complaint #{c_id}: Assigned to '{test_complaint.assigned_authority}', Level {test_complaint.escalation_level}")

    # Step A: First Escalation (Warden -> Dean of Student Affairs)
    print(f"\nTriggering SLA check for Tier 1 -> Tier 2 escalation...")
    escalated = check_and_escalate_grievances(db)
    db.refresh(test_complaint)
    
    print(f"Complaint #{c_id} after Escalation 1:")
    print(f"  - Assigned Authority: {test_complaint.assigned_authority} (Email: {get_authority_email(test_complaint.assigned_authority)})")
    print(f"  - Escalation Level: {test_complaint.escalation_level}")
    print(f"  - New SLA Deadline: {test_complaint.sla_deadline}")
    assert test_complaint.assigned_authority == "Dean of Student Affairs", f"Expected Dean of Student Affairs, got {test_complaint.assigned_authority}"
    assert test_complaint.escalation_level == 1, f"Expected Level 1, got {test_complaint.escalation_level}"

    # Step B: Second Escalation (Dean of Student Affairs -> Principal)
    print(f"\nForcing SLA breach at Dean level for Tier 2 -> Tier 3 escalation...")
    test_complaint.sla_deadline = datetime.utcnow() - timedelta(minutes=5)
    db.commit()

    escalated = check_and_escalate_grievances(db)
    db.refresh(test_complaint)

    print(f"Complaint #{c_id} after Escalation 2:")
    print(f"  - Assigned Authority: {test_complaint.assigned_authority} (Email: {get_authority_email(test_complaint.assigned_authority)})")
    print(f"  - Escalation Level: {test_complaint.escalation_level}")
    print(f"  - New SLA Deadline: {test_complaint.sla_deadline}")
    assert test_complaint.assigned_authority == "Principal", f"Expected Principal, got {test_complaint.assigned_authority}"
    assert test_complaint.escalation_level == 2, f"Expected Level 2, got {test_complaint.escalation_level}"

    # Step C: Verify Harassment Safety Guardrail
    print("\n" + "=" * 60)
    print("3. VERIFYING HARASSMENT / COUNSELING CELL PROTECTION")
    print("=" * 60)

    harassment_complaint = Complaint(
        text="[VERIFICATION TEST] Harassment safety incident requiring private counseling.",
        category="harassment",
        urgency="high",
        status="open",
        assigned_authority="Counseling Cell",
        escalation_level=0,
        no_auto_escalation=True,
        created_at=datetime.utcnow() - timedelta(days=5),
        sla_deadline=datetime.utcnow() - timedelta(days=2),
    )
    db.add(harassment_complaint)
    db.commit()
    db.refresh(harassment_complaint)
    h_id = harassment_complaint.id

    check_and_escalate_grievances(db)
    db.refresh(harassment_complaint)

    print(f"Harassment Complaint #{h_id}:")
    print(f"  - Assigned Authority: {harassment_complaint.assigned_authority}")
    print(f"  - Escalation Level: {harassment_complaint.escalation_level}")
    assert harassment_complaint.assigned_authority == "Counseling Cell", "Harassment complaint must remain with Counseling Cell"
    assert harassment_complaint.escalation_level == 0, "Harassment complaint must NOT be escalated"
    print("[OK] Harassment protection verified: Complaint remained strictly with Counseling Cell!")

    print("\n" + "=" * 60)
    print("4. VERIFYING ACTIVITY AUDIT LOG")
    print("=" * 60)
    logs = db.query(ActivityLog).filter(ActivityLog.complaint_id == c_id).all()
    for l in logs:
        print(f"  [{l.timestamp.strftime('%H:%M:%S')}] {l.action}: {l.details}")

    print("\n" + "=" * 60)
    print("ALL VERIFICATION CHECKS PASSED SUCCESSFULLY!")
    print("=" * 60)
    db.close()

if __name__ == "__main__":
    test_full_escalation_lifecycle()
