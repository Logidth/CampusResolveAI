from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

print("=" * 60)
print("TESTING ADMIN MANAGEMENT, FIRST-LOGIN PASSWORD CHANGE & EXAM CELL")
print("=" * 60)

# 1. Login as logi
res_login = client.post("/auth/login", json={"username": "logi", "password": "admin@1"})
assert res_login.status_code == 200, f"Admin login failed: {res_login.text}"
admin_data = res_login.json()
token = admin_data["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print("1. [OK] Admin 'logi' logged in successfully with password 'admin@1'!")

# 2. List users
res_users = client.get("/admin/users", headers=headers)
assert res_users.status_code == 200
users = res_users.json()
print(f"2. [OK] Admin retrieved {len(users)} registered authorities from database.")

# 3. Create a new authority account
new_auth_payload = {
    "username": "test_exam_officer",
    "password": "tempPass123",
    "full_name": "Dr. Test Exam Officer",
    "role": "Exam Cell Admin",
    "assigned_authority": "Exam Cell Admin",
    "email": "exam2@campus.edu",
    "tier": "Tier 1 — Operational (Marks, Semester & Fees)",
    "must_change_password": True
}
res_create = client.post("/admin/users", json=new_auth_payload, headers=headers)
assert res_create.status_code == 201, f"Create user failed: {res_create.text}"
created_user = res_create.json()
uid = created_user["id"]
uname = created_user["username"]
must_change = created_user["must_change_password"]
print(f"3. [OK] Created authority #{uid} ('{uname}'), must_change_password={must_change}")

# 4. Login as new authority and verify must_change_password flag
res_auth_login = client.post("/auth/login", json={"username": "test_exam_officer", "password": "tempPass123"})
assert res_auth_login.status_code == 200
auth_token = res_auth_login.json()["access_token"]
auth_must_change = res_auth_login.json()["user"]["must_change_password"]
assert auth_must_change is True, "must_change_password should be True on first login"
auth_headers = {"Authorization": f"Bearer {auth_token}"}
print("4. [OK] First-login authority sign-in verified: must_change_password=True flag enforced.")

# 5. Authority changes their password
res_change = client.post("/auth/change-password", json={
    "new_password": "officerSecurePass@2026",
    "confirm_password": "officerSecurePass@2026"
}, headers=auth_headers)
assert res_change.status_code == 200, f"Change password failed: {res_change.text}"
assert res_change.json()["must_change_password"] is False
print("5. [OK] Authority changed password successfully! must_change_password cleared to False.")

# 6. Re-login with the updated password
res_relogin = client.post("/auth/login", json={"username": "test_exam_officer", "password": "officerSecurePass@2026"})
assert res_relogin.status_code == 200
assert res_relogin.json()["user"]["must_change_password"] is False
print("6. [OK] Re-authenticated with newly established password successfully!")

# 7. Test grievance routing to Exam Cell Admin (marks, semester, fee)
res_complaint = client.post("/complaints", json={
    "text": "My semester exam marks are missing in the portal and extra late fee is charged."
})
assert res_complaint.status_code == 201
c_data = res_complaint.json()
print(f"7. [OK] Complaint #{c_data['id']} filed: Category='{c_data['category']}', Routed to='{c_data['assigned_authority']}'")
assert c_data["assigned_authority"] == "Exam Cell Admin", f"Expected Exam Cell Admin, got {c_data['assigned_authority']}"

# 8. Test escalation from Exam Cell Admin -> Dean of Academics
res_breach = client.post(f"/complaints/{c_data['id']}/simulate-breach")
assert res_breach.status_code == 200
b_data = res_breach.json()
print(f"8. [OK] Complaint #{c_data['id']} escalated to: '{b_data['assigned_authority']}' (Level {b_data['escalation_level']})")
assert b_data["assigned_authority"] == "Dean of Academics"

# 9. Clean up test user
res_del = client.delete(f"/admin/users/{uid}", headers=headers)
assert res_del.status_code == 200
print(f"9. [OK] Deleted test authority #{uid}. All API tests PASSED!")
print("=" * 60)
