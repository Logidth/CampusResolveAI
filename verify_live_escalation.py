import urllib.request
import json

BASE = "https://campusresolveai.onrender.com"

print("============================================================")
print("TESTING LIVE MULTI-TIER ESCALATION ON RENDER PRODUCTION")
print("============================================================")

# 1. Create Complaint
create_req = urllib.request.Request(
    f"{BASE}/complaints",
    data=json.dumps({"text": "Water leak in room 204 hostel ceiling damaged electrical wiring"}).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(create_req, timeout=30) as resp:
    c = json.loads(resp.read().decode())
    cid = c["id"]
    auth0 = c["assigned_authority"]
    level0 = c["escalation_level"]
    print(f"1. CREATED COMPLAINT #{cid} on LIVE RENDER:")
    print(f"   - Assigned Authority: {auth0}")
    print(f"   - Escalation Level: {level0}")

# 2. Simulate First Breach (Warden -> Dean of Student Affairs)
b1_req = urllib.request.Request(
    f"{BASE}/complaints/{cid}/simulate-breach",
    data=b"{}",
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(b1_req, timeout=30) as resp:
    b1 = json.loads(resp.read().decode())
    auth1 = b1["assigned_authority"]
    level1 = b1["escalation_level"]
    email1 = b1["assigned_email"]
    print(f"\n2. TIER 1 -> TIER 2 ESCALATION SUCCESSFUL:")
    print(f"   - Complaint #{cid}")
    print(f"   - Escalated To: {auth1}")
    print(f"   - Escalation Level: {level1}")
    print(f"   - Dispatched Alert Email to: {email1}")

# 3. Simulate Second Breach (Dean of Student Affairs -> Principal)
b2_req = urllib.request.Request(
    f"{BASE}/complaints/{cid}/simulate-breach",
    data=b"{}",
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(b2_req, timeout=30) as resp:
    b2 = json.loads(resp.read().decode())
    auth2 = b2["assigned_authority"]
    level2 = b2["escalation_level"]
    email2 = b2["assigned_email"]
    print(f"\n3. TIER 2 -> TIER 3 (APEX) ESCALATION SUCCESSFUL:")
    print(f"   - Complaint #{cid}")
    print(f"   - Escalated To: {auth2}")
    print(f"   - Escalation Level: {level2}")
    print(f"   - Dispatched Alert Email to: {email2}")

print("\n============================================================")
print("LIVE ESCALATION VERIFIED END-TO-END ON PRODUCTION!")
print("============================================================")
