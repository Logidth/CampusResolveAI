"""
Test Suite: Practical Escalation Emails, Authority Deep Links, and Role Queues
Verifies:
1. Multi-domain grievance routing to Tier 1 authorities.
2. Tier 1 -> Tier 2 -> Apex Principal escalations with practical email dispatch.
3. Escalation email content verification (grievance statement, new SLA, direct portal links).
4. Authority resolution with remarks.
5. Role queue isolation and activity log filtering.
"""

import os
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from backend.main import app
from backend.scheduler import check_and_escalate_grievances
from backend.database import SessionLocal, engine, Base
from backend.models import Complaint, ActivityLog
from backend.notifier import get_sent_emails, clear_sent_emails, AUTHORITY_DIRECTORY

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
clear_sent_emails()

print("=" * 65)
print("[START] TESTING PRACTICAL ESCALATION EMAILS & DIRECT DEEP LINKS")
print("=" * 65)

with TestClient(app) as client:
    # 1. Seed Initial Complaints across all domains
    print("\n[INFO] [1/5] Seeding Initial Complaints across 4 Domains:")
    c_hostel = client.post("/complaints", json={"text": "Water leakage and tap broken in hostel room 101"}).json()
    c_mess = client.post("/complaints", json={"text": "Mess dinner food was contaminated and cold"}).json()
    c_acad = client.post("/complaints", json={"text": "Error in academic grades for CS201 exam"}).json()
    c_infra = client.post("/complaints", json={"text": "Campus lift stopped working between floors in building A"}).json()

    print(f"   - Hostel Ticket #{c_hostel['id']} -> Assigned: '{c_hostel['assigned_authority']}' (Expected: Warden)")
    print(f"   - Mess Ticket #{c_mess['id']} -> Assigned: '{c_mess['assigned_authority']}' (Expected: Mess Committee)")
    print(f"   - Academic Ticket #{c_acad['id']} -> Assigned: '{c_acad['assigned_authority']}' (Expected: HOD)")
    print(f"   - Infra Ticket #{c_infra['id']} -> Assigned: '{c_infra['assigned_authority']}' (Expected: Estate Office)")
    
    assert c_hostel["assigned_authority"] == "Warden"
    assert c_mess["assigned_authority"] == "Mess Committee"
    assert c_acad["assigned_authority"] == "HOD"
    assert c_infra["assigned_authority"] == "Estate Office"

    # Verify Initial Level 0 Assignment Emails to Tier 1 Authorities
    warden_emails = client.get("/authority/emails?assigned_authority=Warden").json()
    mess_emails = client.get("/authority/emails?assigned_authority=Mess+Committee").json()
    hod_emails = client.get("/authority/emails?assigned_authority=HOD").json()
    estate_emails = client.get("/authority/emails?assigned_authority=Estate+Office").json()

    print(f"   - Initial Level 0 Email to Warden ({warden_emails[0]['recipient_email']}): {warden_emails[0]['subject'].encode('ascii', 'replace').decode('ascii')}")
    print(f"   - Initial Level 0 Email to Mess Committee ({mess_emails[0]['recipient_email']}): {mess_emails[0]['subject'].encode('ascii', 'replace').decode('ascii')}")
    print(f"   - Initial Level 0 Email to HOD ({hod_emails[0]['recipient_email']}): {hod_emails[0]['subject'].encode('ascii', 'replace').decode('ascii')}")
    print(f"   - Initial Level 0 Email to Estate Office ({estate_emails[0]['recipient_email']}): {estate_emails[0]['subject'].encode('ascii', 'replace').decode('ascii')}")

    assert len(warden_emails) == 1 and warden_emails[0]["recipient_email"] == "dlogidth4@gmail.com"
    assert len(mess_emails) == 1 and mess_emails[0]["recipient_email"] == "dlogidth5@gmail.com"
    assert len(hod_emails) == 1 and hod_emails[0]["recipient_email"] == "717824v101@kce.ac.in"
    assert len(estate_emails) == 1 and estate_emails[0]["recipient_email"] == "717824v134@kce.ac.in"
    assert f"/app/dashboard.html?complaint_id={c_hostel['id']}" in warden_emails[0]["portal_link"]

    # 2. Trigger 1st Escalation Scan (Tier 1 -> Tier 2)
    print("\n[INFO] [2/5] Triggering 1st Escalation Scan (Tier 1 -> Tier 2):")
    db = SessionLocal()
    for c in db.query(Complaint).all():
        c.sla_deadline = datetime.utcnow() - timedelta(hours=10)
    db.commit()

    check_and_escalate_grievances(db)

    c1 = db.query(Complaint).filter(Complaint.id == c_hostel["id"]).first()
    c2 = db.query(Complaint).filter(Complaint.id == c_mess["id"]).first()
    c3 = db.query(Complaint).filter(Complaint.id == c_acad["id"]).first()
    c4 = db.query(Complaint).filter(Complaint.id == c_infra["id"]).first()

    print(f"   - #{c1.id} Escalated: '{c1.assigned_authority}' (Expected: Dean of Student Affairs)")
    print(f"   - #{c2.id} Escalated: '{c2.assigned_authority}' (Expected: Dean of Student Affairs)")
    print(f"   - #{c3.id} Escalated: '{c3.assigned_authority}' (Expected: Dean of Academics)")
    print(f"   - #{c4.id} Escalated: '{c4.assigned_authority}' (Expected: Vice Principal)")

    assert c1.assigned_authority == "Dean of Student Affairs"
    assert c2.assigned_authority == "Dean of Student Affairs"
    assert c3.assigned_authority == "Dean of Academics"
    assert c4.assigned_authority == "Vice Principal"

    # 3. Verify Practical Escalation Emails Dispatched & Direct Deep Links
    print("\n[INFO] [3/5] Verifying Practical Escalation Emails & Portal Deep Links:")
    emails_dean_students = client.get("/authority/emails?assigned_authority=Dean+of+Student+Affairs").json()
    emails_dean_academics = client.get("/authority/emails?assigned_authority=Dean+of+Academics").json()
    emails_vp = client.get("/authority/emails?assigned_authority=Vice+Principal").json()

    print(f"   - Emails received by Dean of Student Affairs: {len(emails_dean_students)} (Expected: 2)")
    print(f"      Practical Recipient Email: {emails_dean_students[0]['recipient_email']}")
    print(f"      Direct Portal Link: {emails_dean_students[0]['portal_link']}")
    assert len(emails_dean_students) == 2
    assert "abijithmohanan2006@gmail.com" in emails_dean_students[0]["recipient_email"]
    assert f"/app/dashboard.html?complaint_id={c2.id}" in emails_dean_students[0]["portal_link"]
    assert "dashboard.html" in emails_dean_students[0]["body"]

    print(f"   - Emails received by Dean of Academics: {len(emails_dean_academics)} (Expected: 1)")
    print(f"      Practical Recipient Email: {emails_dean_academics[0]['recipient_email']}")
    assert len(emails_dean_academics) == 1
    assert "717824v101@kce.ac.in" in emails_dean_academics[0]["recipient_email"]

    print(f"   - Emails received by Vice Principal: {len(emails_vp)} (Expected: 1)")
    print(f"      Practical Recipient Email: {emails_vp[0]['recipient_email']}")
    assert len(emails_vp) == 1
    assert "logidth78@gmail.com" in emails_vp[0]["recipient_email"]

    # 4. Trigger 2nd Escalation Scan (Tier 2 -> Principal)
    print("\n[INFO] [4/5] Triggering 2nd Escalation Scan (Tier 2 -> Principal):")
    c1.sla_deadline = datetime.utcnow() - timedelta(hours=10)
    db.commit()

    check_and_escalate_grievances(db)
    db.refresh(c1)

    print(f"   - #{c1.id} Escalated to Apex: '{c1.assigned_authority}' (Expected: Principal) | Level {c1.escalation_level}")
    assert c1.assigned_authority == "Principal"
    assert c1.escalation_level == 2

    emails_principal = client.get("/authority/emails?assigned_authority=Principal").json()
    print(f"   - Emails received by Principal: {len(emails_principal)} (Expected: 1)")
    print(f"      Practical Recipient Email: {emails_principal[0]['recipient_email']}")
    assert len(emails_principal) == 1
    assert "717824v127@kce.ac.in" in emails_principal[0]["recipient_email"]

    # 5. Test Resolution with Remarks & Filtered Role Queues
    print("\n[INFO] [5/5] Testing Resolution with Official Remarks & Queue Filtering:")
    resolve_res = client.patch(f"/complaints/{c1.id}/resolve", json={
        "remarks": "Principal office intervened. Plumbing vendor dispatched to replace leaking valve."
    })
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "resolved"

    resolved_detail = client.get(f"/complaints/{c1.id}").json()
    latest_log = resolved_detail["activity_logs"][-1]
    assert latest_log["action"] == "RESOLVED"
    assert "Plumbing vendor dispatched" in latest_log["details"]
    print(f"   [PASS] Resolution logged with remarks: {latest_log['details']}")

    # Check Dean of Student Affairs Queue
    dean_q = client.get("/complaints?assigned_authority=Dean+of+Student+Affairs&status=open").json()
    assert len(dean_q) == 1
    assert dean_q[0]["id"] == c2.id
    print(f"   [PASS] Dean Queue isolated to ticket #{dean_q[0]['id']}")

    print("\n" + "=" * 65)
    print("[SUCCESS] ALL PRACTICAL EMAIL & DIRECT DEEP LINK TESTS PASSED!")
    print("=" * 65)
