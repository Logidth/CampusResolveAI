from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

# 1. Create a mess complaint
res = client.post("/complaints", json={"text": "Mess food is cold and unhygienic in Block B dining hall."})
assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.text}"
data = res.json()
c_id = data["id"]
auth = data["assigned_authority"]
level = data["escalation_level"]
print(f"Created Complaint #{c_id}: Assigned to '{auth}', Escalation Level {level}")
assert auth == "Mess Committee", f"Expected Mess Committee, got {auth}"
assert level == 0, f"Expected level 0, got {level}"

# 2. Simulate first breach (Mess Committee -> Dean of Student Affairs)
res_breach1 = client.post(f"/complaints/{c_id}/simulate-breach")
assert res_breach1.status_code == 200, f"Expected 200, got {res_breach1.status_code}: {res_breach1.text}"
b1_data = res_breach1.json()
print(f"Breach 1 Result: Escalated to '{b1_data['assigned_authority']}' (Level {b1_data['escalation_level']}), Email: {b1_data['assigned_email']}")
assert b1_data["assigned_authority"] == "Dean of Student Affairs"
assert b1_data["escalation_level"] == 1
assert b1_data["assigned_email"] == "abijithmohanan2006@gmail.com"

# 3. Simulate second breach (Dean of Student Affairs -> Principal)
res_breach2 = client.post(f"/complaints/{c_id}/simulate-breach")
assert res_breach2.status_code == 200, f"Expected 200, got {res_breach2.status_code}: {res_breach2.text}"
b2_data = res_breach2.json()
print(f"Breach 2 Result: Escalated to '{b2_data['assigned_authority']}' (Level {b2_data['escalation_level']}), Email: {b2_data['assigned_email']}")
assert b2_data["assigned_authority"] == "Principal"
assert b2_data["escalation_level"] == 2
assert b2_data["assigned_email"] == "717824v132@kce.ac.in"

# 4. Verify admin escalate check endpoint
res_admin = client.post("/admin/escalate-check")
assert res_admin.status_code == 200
print("Admin escalate check response:", res_admin.json())

print("\nAll API escalation endpoints passed and verified!")
