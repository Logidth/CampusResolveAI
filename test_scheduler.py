import os
os.environ['MOCK_MODE'] = 'true'
os.environ['DEBUG_TIME_SCALE'] = '3600' # 1 real second = 1 simulated hour

from datetime import datetime, timedelta
import time
from fastapi.testclient import TestClient
from backend.main import app
from backend.scheduler import check_and_escalate_grievances, get_sla_duration, get_next_authority, scheduler
from backend.database import SessionLocal, engine, Base
from backend.models import Complaint, ActivityLog

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

print("=" * 65)
print("[START] TESTING SCHEDULER, TIERED ESCALATION & TIME SCALING")
print("=" * 65)

# --- 1. TEST TIME SCALING HELPER ---
delta_high = get_sla_duration("high")
delta_med = get_sla_duration("medium")
delta_low = get_sla_duration("low")
print(f"[INFO] Scaled Durations (DEBUG_TIME_SCALE=3600):")
print(f"   - High (nominal 6h): {delta_high.total_seconds()} seconds (expected 6s)")
print(f"   - Medium (nominal 48h): {delta_med.total_seconds()} seconds (expected 48s)")
print(f"   - Low (nominal 168h): {delta_low.total_seconds()} seconds (expected 168s)")
assert delta_high.total_seconds() == 6.0
assert delta_med.total_seconds() == 48.0
assert delta_low.total_seconds() == 168.0
print("[PASS] Time scaling helper verified.")

# --- 2. TEST AUTHORITY ESCALATION TIERS ---
assert get_next_authority("Warden") == "Dean of Student Affairs"
assert get_next_authority("Mess Committee") == "Dean of Student Affairs"
assert get_next_authority("HOD") == "Dean of Academics"
assert get_next_authority("Estate Office") == "Vice Principal"
assert get_next_authority("Dean of Student Affairs") == "Principal"
assert get_next_authority("Dean of Academics") == "Principal"
assert get_next_authority("Vice Principal") == "Principal"
print("[PASS] Escalation authority mapping hierarchy verified.")

# --- 3. TEST STEP-BY-STEP ESCALATION WITH EXTENDED DEADLINE & LOGS ---
db = SessionLocal()
now = datetime.utcnow()

# Seed complaints
c_warden = Complaint(
    text="Water issue in hostel",
    category="hostel",
    urgency="high",
    status="open",
    assigned_authority="Warden",
    escalation_level=0,
    no_auto_escalation=False,
    created_at=now,
    sla_deadline=now - timedelta(seconds=10) # already breached
)
c_hod = Complaint(
    text="Exam discrepancy",
    category="academic",
    urgency="medium",
    status="open",
    assigned_authority="HOD",
    escalation_level=0,
    no_auto_escalation=False,
    created_at=now,
    sla_deadline=now - timedelta(seconds=10)
)
c_harass = Complaint(
    text="Harassment reported",
    category="harassment",
    urgency="high",
    status="open",
    assigned_authority="Counseling Cell",
    escalation_level=0,
    no_auto_escalation=True,
    created_at=now,
    sla_deadline=now - timedelta(seconds=10)
)
db.add_all([c_warden, c_hod, c_harass])
db.commit()

# Run 1st escalation check
check_and_escalate_grievances(db)

db.refresh(c_warden)
db.refresh(c_hod)
db.refresh(c_harass)

# 1st Escalation assertions
print(f"\n[INFO] After 1st Escalation Scan:")
print(f"   - c_warden: level={c_warden.escalation_level}, authority='{c_warden.assigned_authority}'")
print(f"   - c_hod:    level={c_hod.escalation_level}, authority='{c_hod.assigned_authority}'")
print(f"   - c_harass: level={c_harass.escalation_level}, authority='{c_harass.assigned_authority}'")

assert c_warden.escalation_level == 1
assert c_warden.assigned_authority == "Dean of Student Affairs"
assert c_hod.escalation_level == 1
assert c_hod.assigned_authority == "Dean of Academics"
assert c_harass.escalation_level == 0
assert c_harass.assigned_authority == "Counseling Cell"

# Check activity log entry text
logs_warden = db.query(ActivityLog).filter(ActivityLog.complaint_id == c_warden.id, ActivityLog.action == "ESCALATED").all()
assert len(logs_warden) == 1
assert "Escalated from Warden to Dean of Student Affairs" in logs_warden[0].details
print(f"[PASS] 1st Escalation Log verified: '{logs_warden[0].details}'")

# Simulate 2nd SLA breach on c_warden to test escalation to Principal
c_warden.sla_deadline = datetime.utcnow() - timedelta(seconds=10)
db.commit()

check_and_escalate_grievances(db)
db.refresh(c_warden)

print(f"\n[INFO] After 2nd Escalation Scan on c_warden:")
print(f"   - c_warden: level={c_warden.escalation_level}, authority='{c_warden.assigned_authority}'")
assert c_warden.escalation_level == 2
assert c_warden.assigned_authority == "Principal"

logs_warden2 = db.query(ActivityLog).filter(ActivityLog.complaint_id == c_warden.id, ActivityLog.action == "ESCALATED").all()
assert len(logs_warden2) == 2
assert logs_warden2[1].details.startswith("Escalated from Dean of Student Affairs to Principal")
print(f"[PASS] 2nd Escalation Log verified: '{logs_warden2[1].details}'")

db.close()

# --- 4. TEST FASTAPI LIFESPAN INTEGRATION ---
with TestClient(app) as client:
    r = client.get("/")
    assert r.status_code == 200
    assert scheduler.running is True
    print("[PASS] FastAPI Lifespan boot: APScheduler is active and running background job.")

print("=" * 65)
print("[SUCCESS] ALL SCHEDULER, TIERED ESCALATION & DEBUG_TIME_SCALE TESTS PASSED!")
print("=" * 65)
