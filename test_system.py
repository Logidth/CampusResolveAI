import os
os.environ['MOCK_MODE'] = 'true'

from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from backend.main import app
from backend.scheduler import check_and_escalate_grievances
from backend.database import SessionLocal, engine, Base
from backend.models import Complaint, ActivityLog

# Re-create clean tables for test run
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

client = TestClient(app)

print('=' * 65)
print('[START] STARTING CAMPUSRESOLVE END-TO-END TEST SUITE')
print('=' * 65)

# --- 1. HEALTH CHECK ---
r_health = client.get('/health')
assert r_health.status_code == 200
assert r_health.json() == {'status': 'CampusResolve agent running'}
print('[PASS] [1/6] Health Check GET /health: OK ->', r_health.json())

# --- 2. TEST ALL CATEGORIES, ROUTING & SLAs ---
test_cases = [
    {
        'text': 'The bathroom geyser and tap water are not working in hostel room 204',
        'expected_cat': 'hostel',
        'expected_auth': 'Warden',
    },
    {
        'text': 'Uncooked food and unhygienic breakfast served in the student mess hall',
        'expected_cat': 'mess',
        'expected_auth': 'Mess Committee',
    },
    {
        'text': 'Exam grades for CS101 lecture were miscalculated and attendance not marked',
        'expected_cat': 'academic',
        'expected_auth': 'HOD',
    },
    {
        'text': 'Broken laboratory bench, faulty AC, and flickering tube light in building B',
        'expected_cat': 'infrastructure',
        'expected_auth': 'Estate Office',
    },
    {
        'text': 'Urgent: seniors are ragging and verbally threatening freshers in hallway',
        'expected_cat': 'harassment',
        'expected_auth': 'Counseling Cell',
        'expected_urgency': 'high',
        'expected_no_auto_esc': True,
        'expected_sla_hours': 6,
    },
]

print('\n[INFO] [2/6] Testing Autonomous AI Agent Triage for all 5 Categories:')
created_ids = []
for i, tc in enumerate(test_cases, 1):
    res = client.post('/complaints', json={'text': tc['text']})
    assert res.status_code == 201, f'Failed on test case {i}: {res.text}'
    data = res.json()
    created_ids.append(data['id'])
    
    assert data['category'] == tc['expected_cat']
    assert data['assigned_authority'] == tc['expected_auth']
    
    if 'expected_urgency' in tc:
        assert data['urgency'] == tc['expected_urgency']
    if 'expected_no_auto_esc' in tc:
        assert data['no_auto_escalation'] == tc['expected_no_auto_esc']
    if 'expected_sla_hours' in tc:
        created_dt = datetime.fromisoformat(data['created_at'])
        sla_dt = datetime.fromisoformat(data['sla_deadline'])
        hours_diff = round((sla_dt - created_dt).total_seconds() / 3600)
        assert hours_diff == tc['expected_sla_hours']
        
    print(f'   - [{data["category"].upper()}] #{data["id"]} -> Assigned: "{data["assigned_authority"]}" | Urgency: "{data["urgency"]}" | Auto-Escalation Locked: {data["no_auto_escalation"]}')

# --- 3. LIST ALL COMPLAINTS ---
r_list = client.get('/complaints?include_harassment=true')
assert r_list.status_code == 200
all_complaints = r_list.json()
assert len(all_complaints) == 5
print(f'\n[PASS] [3/6] GET /complaints: Successfully listed {len(all_complaints)} complaints (with harassment).')

# --- 4. AUDIT & ACTIVITY LOG VALIDATION ---
harass_id = created_ids[4]
r_harass = client.get(f'/complaints/{harass_id}')
assert r_harass.status_code == 200
harass_data = r_harass.json()
assert len(harass_data['activity_logs']) >= 1
first_log = harass_data['activity_logs'][0]
assert first_log['action'] == 'CLASSIFICATION'
assert 'Classified as harassment/high, routed to Counseling Cell' in first_log['details']
print('\n[PASS] [4/6] Activity Log & Audit Trail for Harassment Ticket:')
print(f'   Log Details: "{first_log["details"]}"')

# --- 5. SCHEDULER ESCALATION & SAFETY GUARDRAIL TEST ---
print('\n[INFO] [5/6] Testing Automated Escalation vs Harassment Protection:')
db = SessionLocal()
# Simulate SLA breach by setting sla_deadline 5 hours in the past
for c in db.query(Complaint).all():
    c.sla_deadline = datetime.utcnow() - timedelta(hours=5)
db.commit()

check_and_escalate_grievances(db)

for c in db.query(Complaint).all():
    if c.category == 'harassment':
        assert c.escalation_level == 0, 'Harassment ticket was escalated! Safety violation!'
        print(f'   - Harassment Ticket #{c.id}: Escalation Level = {c.escalation_level} (IMMUNE to auto-escalation)')
    else:
        assert c.escalation_level == 1, f'Ticket #{c.id} failed to escalate!'
        print(f'   - {c.category.capitalize()} Ticket #{c.id}: Escalation Level = {c.escalation_level} (Escalated properly)')
db.close()

# --- 6. RESOLVE COMPLAINT ---
target_id = created_ids[0]
r_resolve = client.patch(f'/complaints/{target_id}/resolve')
assert r_resolve.status_code == 200
resolved_item = r_resolve.json()
assert resolved_item['status'] == 'resolved'
assert resolved_item['resolved_at'] is not None

r_resolved_detail = client.get(f'/complaints/{target_id}')
logs = r_resolved_detail.json()['activity_logs']
assert any(l['action'] == 'RESOLVED' for l in logs)
print(f'\n[PASS] [6/6] PATCH /complaints/{target_id}/resolve: Status = "{resolved_item["status"]}", Resolved At = {resolved_item["resolved_at"]}')

print('\n' + '=' * 65)
print('[SUCCESS] ALL TESTS PASSED (6/6)! SYSTEM VERIFIED.')
print('=' * 65)
