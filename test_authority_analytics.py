import os
import sys
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import get_db
from backend.models import Complaint, ActivityLog, User
from backend.auth import create_session_token, hash_password, seed_authority_users

client = TestClient(app)


def test_principal_analytics_authorization_gating():
    print("\n--- Test 1: Principal Analytics Access Control Gating ---")
    db = next(get_db())
    try:
        seed_authority_users(db)
        # 1. Anonymous request -> 401 Unauthorized
        res_anon = client.get("/principal/analytics/authority-report")
        assert res_anon.status_code == 401, f"Expected 401 Unauthorized, got {res_anon.status_code}"
        print("[Pass] Anonymous access correctly returned 401 Unauthorized")

        # 2. Student user -> 403 Forbidden
        student_user = db.query(User).filter(User.role == "Student").first()
        if not student_user:
            student_user = User(
                username="test_student_analytics",
                email="test_student@kce.ac.in",
                hashed_password=hash_password("pass123"),
                full_name="Test Student",
                role="Student",
                tier="Student"
            )
            db.add(student_user)
            db.commit()
            db.refresh(student_user)
        student_token = create_session_token(student_user)
        res_student = client.get(
            "/principal/analytics/authority-report",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        assert res_student.status_code == 403, f"Expected 403 Forbidden for Student, got {res_student.status_code}"
        print("[Pass] Student role correctly returned 403 Forbidden")

        # 3. Warden user -> 403 Forbidden
        warden_user = db.query(User).filter(User.username == "warden").first()
        assert warden_user is not None, "Warden account should be seeded"
        warden_token = create_session_token(warden_user)
        res_warden = client.get(
            "/principal/analytics/authority-report",
            headers={"Authorization": f"Bearer {warden_token}"}
        )
        assert res_warden.status_code == 403, f"Expected 403 Forbidden for Warden, got {res_warden.status_code}"
        print("[Pass] Warden role correctly returned 403 Forbidden")

        # 4. Admin user -> 403 Forbidden (Principal role strictly required)
        admin_user = db.query(User).filter(User.username == "logi").first()
        assert admin_user is not None, "Admin account should be seeded"
        admin_token = create_session_token(admin_user)
        res_admin = client.get(
            "/principal/analytics/authority-report",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res_admin.status_code == 403, f"Expected 403 Forbidden for Admin, got {res_admin.status_code}"
        print("[Pass] Central Admin role correctly returned 403 Forbidden")

        # 5. Principal user -> 200 OK
        principal_user = db.query(User).filter(User.username == "principal").first()
        assert principal_user is not None, "Principal account should be seeded"
        principal_token = create_session_token(principal_user)
        res_principal = client.get(
            "/principal/analytics/authority-report",
            headers={"Authorization": f"Bearer {principal_token}"}
        )
        assert res_principal.status_code == 200, f"Expected 200 OK for Principal, got {res_principal.status_code}"
        print("[Pass] Principal role successfully authenticated with 200 OK")

    finally:
        db.close()


def test_principal_analytics_metrics_and_sorting():
    print("\n--- Test 2: Principal Authority Analytics Metrics, Grouping & Sorting ---")
    db = next(get_db())
    try:
        # Clear existing test complaints and activity logs for deterministic assertion
        db.query(ActivityLog).delete()
        db.query(Complaint).delete()
        db.commit()

        now = datetime.utcnow()

        # Seed Warden Complaints (Total: 4, Resolved: 2, Escalated: 2, Disputed: 1)
        # Warden 1: Resolved in 4.0 hours, escalation 0
        w1 = Complaint(
            text="Warden issue 1",
            category="hostel",
            urgency="medium",
            status="resolved",
            assigned_authority="Warden",
            initial_authority="Warden",
            ticket_id="w_t1",
            escalation_level=0,
            created_at=now - timedelta(hours=10),
            resolved_at=now - timedelta(hours=6)
        )
        # Warden 2: Resolved in 6.0 hours, escalation 1
        w2 = Complaint(
            text="Warden issue 2",
            category="hostel",
            urgency="high",
            status="resolved",
            assigned_authority="Dean of Student Affairs",
            initial_authority="Warden",
            ticket_id="w_t2",
            escalation_level=1,
            created_at=now - timedelta(hours=20),
            resolved_at=now - timedelta(hours=14)
        )
        # Warden 3: Open, escalation 0
        w3 = Complaint(
            text="Warden issue 3",
            category="hostel",
            urgency="low",
            status="open",
            assigned_authority="Warden",
            initial_authority="Warden",
            ticket_id="w_t3",
            escalation_level=0,
            created_at=now - timedelta(hours=8)
        )
        # Warden 4: Open, escalation 2, Disputed to Principal
        w4 = Complaint(
            text="Warden issue 4",
            category="hostel",
            urgency="urgent",
            status="open",
            assigned_authority="Principal",
            initial_authority="Warden",
            ticket_id="w_t4",
            escalation_level=2,
            created_at=now - timedelta(hours=24)
        )
        db.add_all([w1, w2, w3, w4])
        db.commit()
        db.refresh(w4)

        # Add ActivityLog for dispute on w4
        log_w4 = ActivityLog(
            complaint_id=w4.id,
            action="DISPUTED_TO_PRINCIPAL",
            details="Student disputed fake resolution by Warden",
            timestamp=now - timedelta(hours=12)
        )
        db.add(log_w4)

        # Seed Mess Committee Complaints (Total: 3, Resolved: 1, Escalated: 1, Disputed: 0)
        # Mess 1: Resolved in 2.0 hours
        m1 = Complaint(
            text="Mess issue 1",
            category="mess",
            urgency="low",
            status="resolved",
            assigned_authority="Mess Committee",
            initial_authority="Mess Committee",
            ticket_id="m_t1",
            escalation_level=0,
            created_at=now - timedelta(hours=5),
            resolved_at=now - timedelta(hours=3)
        )
        # Mess 2: Open
        m2 = Complaint(
            text="Mess issue 2",
            category="mess",
            urgency="medium",
            status="open",
            assigned_authority="Mess Committee",
            initial_authority="Mess Committee",
            ticket_id="m_t2",
            escalation_level=0,
            created_at=now - timedelta(hours=4)
        )
        # Mess 3: Open, Escalated 1
        m3 = Complaint(
            text="Mess issue 3",
            category="mess",
            urgency="high",
            status="open",
            assigned_authority="Dean of Student Affairs",
            initial_authority="Mess Committee",
            ticket_id="m_t3",
            escalation_level=1,
            created_at=now - timedelta(hours=15)
        )
        db.add_all([m1, m2, m3])

        # Seed Estate Office Complaints (Total: 2, Resolved: 2, Escalated: 0, Disputed: 0)
        # Estate 1: Resolved in 8.0 hours
        e1 = Complaint(
            text="Estate issue 1",
            category="infrastructure",
            urgency="medium",
            status="resolved",
            assigned_authority="Estate Office",
            initial_authority="Estate Office",
            ticket_id="e_t1",
            escalation_level=0,
            created_at=now - timedelta(hours=12),
            resolved_at=now - timedelta(hours=4)
        )
        # Estate 2: Resolved in 4.0 hours
        e2 = Complaint(
            text="Estate issue 2",
            category="infrastructure",
            urgency="low",
            status="resolved",
            assigned_authority="Estate Office",
            initial_authority="Estate Office",
            ticket_id="e_t2",
            escalation_level=0,
            created_at=now - timedelta(hours=8),
            resolved_at=now - timedelta(hours=4)
        )
        db.add_all([e1, e2])

        # Seed Exam Cell Admin Complaints (Total: 1, Resolved: 0, Escalated: 1, Disputed: 1)
        ex1 = Complaint(
            text="Exam issue 1",
            category="academic",
            urgency="high",
            status="open",
            assigned_authority="Dean of Academics",
            initial_authority="Exam Cell Admin",
            ticket_id="ex_t1",
            escalation_level=1,
            created_at=now - timedelta(hours=18)
        )
        db.add(ex1)
        db.commit()
        db.refresh(ex1)

        log_ex1 = ActivityLog(
            complaint_id=ex1.id,
            action="DISPUTED_TO_PRINCIPAL",
            details="Student disputed marks review grievance",
            timestamp=now - timedelta(hours=6)
        )
        db.add(log_ex1)
        db.commit()

        # Login as Principal
        principal_user = db.query(User).filter(User.username == "principal").first()
        principal_token = create_session_token(principal_user)

        res = client.get(
            "/principal/analytics/authority-report",
            headers={"Authorization": f"Bearer {principal_token}"}
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()

        authorities = data["authorities"]
        summary = data["summary"]

        print(f"[Check] Returned {len(authorities)} authority rows.")

        # 1. Assert Descending Sort Order by total_raised
        auth_names = [a["authority"] for a in authorities]
        assert auth_names == ["Warden", "Mess Committee", "Estate Office", "Exam Cell Admin"], f"Unexpected sort order: {auth_names}"
        print("[Pass] Authorities sorted descending by total_raised: Warden (4), Mess (3), Estate (2), Exam Cell (1)")

        # 2. Verify Warden Metrics
        warden_row = next(a for a in authorities if a["authority"] == "Warden")
        assert warden_row["total_raised"] == 4, f"Warden total_raised expected 4, got {warden_row['total_raised']}"
        assert warden_row["total_resolved"] == 2, f"Warden total_resolved expected 2, got {warden_row['total_resolved']}"
        assert warden_row["total_escalated"] == 2, f"Warden total_escalated expected 2, got {warden_row['total_escalated']}"
        assert warden_row["total_disputed"] == 1, f"Warden total_disputed expected 1, got {warden_row['total_disputed']}"
        assert warden_row["avg_resolution_time_hours"] == 5.0, f"Warden avg_resolution_time_hours expected 5.0, got {warden_row['avg_resolution_time_hours']}"
        assert warden_row["resolution_rate_percent"] == 50.0, f"Warden resolution_rate_percent expected 50.0, got {warden_row['resolution_rate_percent']}"
        print("[Pass] Warden row metrics verified.")

        # 3. Verify Mess Committee Metrics
        mess_row = next(a for a in authorities if a["authority"] == "Mess Committee")
        assert mess_row["total_raised"] == 3
        assert mess_row["total_resolved"] == 1
        assert mess_row["total_escalated"] == 1
        assert mess_row["total_disputed"] == 0
        assert mess_row["avg_resolution_time_hours"] == 2.0
        assert mess_row["resolution_rate_percent"] == 33.3
        print("[Pass] Mess Committee row metrics verified.")

        # 4. Verify Estate Office Metrics
        estate_row = next(a for a in authorities if a["authority"] == "Estate Office")
        assert estate_row["total_raised"] == 2
        assert estate_row["total_resolved"] == 2
        assert estate_row["total_escalated"] == 0
        assert estate_row["total_disputed"] == 0
        assert estate_row["avg_resolution_time_hours"] == 6.0
        assert estate_row["resolution_rate_percent"] == 100.0
        print("[Pass] Estate Office row metrics verified.")

        # 5. Verify Exam Cell Admin Metrics
        exam_row = next(a for a in authorities if a["authority"] == "Exam Cell Admin")
        assert exam_row["total_raised"] == 1
        assert exam_row["total_resolved"] == 0
        assert exam_row["total_escalated"] == 1
        assert exam_row["total_disputed"] == 1
        assert exam_row["avg_resolution_time_hours"] == 0.0
        assert exam_row["resolution_rate_percent"] == 0.0
        print("[Pass] Exam Cell Admin row metrics verified.")

        # 6. Verify Overall Summary
        assert summary["authority"] == "Overall"
        assert summary["total_raised"] == 10
        assert summary["total_resolved"] == 5
        assert summary["total_escalated"] == 4
        assert summary["total_disputed"] == 2
        # (4.0 + 6.0 + 2.0 + 8.0 + 4.0) / 5 = 24.0 / 5 = 4.8
        assert summary["avg_resolution_time_hours"] == 4.8, f"Summary avg_resolution_time_hours expected 4.8, got {summary['avg_resolution_time_hours']}"
        assert summary["resolution_rate_percent"] == 50.0, f"Summary resolution_rate_percent expected 50.0, got {summary['resolution_rate_percent']}"
        print("[Pass] Overall Summary metrics verified.")

        print("\nALL PRINCIPAL ANALYTICS ASSERTIONS PASSED SUCCESSFULLY!")

    finally:
        db.close()


if __name__ == "__main__":
    test_principal_analytics_authorization_gating()
    test_principal_analytics_metrics_and_sorting()
