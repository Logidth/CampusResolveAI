import sys
import os
from fastapi.testclient import TestClient

from backend.main import app
from backend.notifier import get_sent_emails, get_authority_email, AUTHORITY_DIRECTORY

client = TestClient(app)

def test_authority_dispute_flow():
    print("\n--- Starting Authority Dispute / Fake Resolution Test ---")

    # 1. Verify Principal email is configured to 717824v132@kce.ac.in
    principal_email = get_authority_email("Principal")
    print(f"[Check 1] Principal configured email: {principal_email}")
    assert principal_email == "717824v132@kce.ac.in", f"Expected 717824v132@kce.ac.in, got {principal_email}"

    # 2. Authenticate Student A (717824v199@kce.ac.in)
    res_auth_a = client.post("/auth/student-login", json={
        "email": "717824v199@kce.ac.in",
        "password": "Password123!",
        "full_name": "Student A"
    })
    assert res_auth_a.status_code == 200, f"Student A login failed: {res_auth_a.text}"
    token_a = res_auth_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 3. Authenticate Student B (717824v198@kce.ac.in)
    res_auth_b = client.post("/auth/student-login", json={
        "email": "717824v198@kce.ac.in",
        "password": "Password123!",
        "full_name": "Student B"
    })
    assert res_auth_b.status_code == 200, f"Student B login failed: {res_auth_b.text}"
    token_b = res_auth_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 4. Student A lodges a complaint
    res_create = client.post("/complaints", json={
        "text": "Water purifier in Hostel C 2nd floor is dispensing yellow murky water.",
        "student_email": "717824v199@kce.ac.in",
        "student_name": "Student A"
    }, headers=headers_a)
    assert res_create.status_code == 201, f"Create failed: {res_create.text}"
    c_data = res_create.json()
    ticket_id = c_data["ticket_id"]
    complaint_id = c_data["id"]
    orig_authority = c_data["assigned_authority"]
    print(f"[Check 2] Student A lodged grievance #{complaint_id} with ticket '{ticket_id}', assigned to '{orig_authority}'")
    assert "v199_t" in ticket_id, f"Expected v199 prefix, got {ticket_id}"

    # 5. Authority resolves the complaint (simulating a 'fake resolution')
    res_resolve = client.patch(f"/complaints/{complaint_id}/resolve", json={
        "remarks": "Purifier filter checked and flushed clean."
    })
    assert res_resolve.status_code == 200
    print(f"[Check 3] Complaint marked resolved with remarks by {orig_authority}")

    # 6. Student B tries to dispute Student A's ticket (must be restricted with 403 Forbidden)
    res_dispute_b = client.post(f"/complaints/{ticket_id}/dispute", json={
        "reason": "Fake Resolution",
        "description": "Student B trying to hijack ticket."
    }, headers=headers_b)
    print(f"[Check 4] Student B dispute attempt status code: {res_dispute_b.status_code}")
    assert res_dispute_b.status_code == 403, f"Expected 403 Forbidden, got {res_dispute_b.status_code}"

    # 7. Student A disputes the resolution and reports the authority to the Principal
    emails_before = len(get_sent_emails(authority="Principal"))
    res_dispute_a = client.post(f"/complaints/{ticket_id}/dispute", json={
        "reason": "Fake Resolution (Claimed resolved without fixing)",
        "description": "The technician only wiped the outside of the machine. The water coming out is still yellowish and smells foul. Please urgently inspect."
    }, headers=headers_a)
    assert res_dispute_a.status_code == 200, f"Dispute failed: {res_dispute_a.text}"
    dispute_res = res_dispute_a.json()
    print(f"[Check 5] Student A dispute response: {dispute_res}")
    assert dispute_res["status"] == "success"
    assert dispute_res["assigned_authority"] == "Principal"
    assert dispute_res["complaint_status"] == "open"
    assert "717824v132@kce.ac.in" in dispute_res["message"]

    # 8. Check complaint details in database
    res_detail = client.get(f"/complaints/{ticket_id}", headers=headers_a)
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["status"] == "open"
    assert detail["assigned_authority"] == "Principal"
    assert detail["escalation_level"] == 2
    print(f"[Check 6] Ticket #{ticket_id} verified re-opened, assigned to Principal at Level 2")

    # Check activity logs for DISPUTED_TO_PRINCIPAL
    log_actions = [log["action"] for log in detail["activity_logs"]]
    print(f"[Check 7] Activity logs: {log_actions}")
    assert "DISPUTED_TO_PRINCIPAL" in log_actions
    dispute_log = [log for log in detail["activity_logs"] if log["action"] == "DISPUTED_TO_PRINCIPAL"][0]
    assert "technician only wiped the outside" in dispute_log["details"]

    # 9. Verify Email was queued to Principal (717824v132@kce.ac.in)
    emails_after = get_sent_emails(authority="Principal")
    print(f"[Check 8] Total emails sent to Principal (717824v132@kce.ac.in): {len(emails_after)}")
    assert len(emails_after) > emails_before, "No email was sent to Principal!"
    latest_email = emails_after[0]
    print(f"   Subject: {latest_email['subject'].encode('ascii', 'replace').decode()}")
    print(f"   Recipient: {latest_email['recipient_email']}")
    assert "717824v132@kce.ac.in" in latest_email["recipient_email"]
    assert ticket_id in latest_email["subject"] or str(complaint_id) in latest_email["subject"]

    print("\nSUCCESS: All tests for authority dispute and email dispatch to 717824v132@kce.ac.in passed cleanly!")

if __name__ == "__main__":
    test_authority_dispute_flow()
