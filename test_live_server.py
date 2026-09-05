import urllib.request
import json

def post(url, data):
    req = urllib.request.Request(
        url, 
        data=json.dumps(data).encode('utf-8'), 
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def get(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def patch(url, data):
    req = urllib.request.Request(
        url, 
        data=json.dumps(data).encode('utf-8'), 
        headers={'Content-Type': 'application/json'},
        method='PATCH'
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

print("=== [1/3] Submitting Grievances to Live Server ===")
c_hostel = post("http://127.0.0.1:8000/complaints", {"text": "H-block water supply is insufficient"})
print(f"Hostel Ticket #{c_hostel['id']} -> Assigned: {c_hostel['assigned_authority']} (Category: {c_hostel['category']})")
assert c_hostel['assigned_authority'] == "Warden"

c_infra = post("http://127.0.0.1:8000/complaints", {"text": "c101 bench is broken"})
print(f"Infra Ticket #{c_infra['id']} -> Assigned: {c_infra['assigned_authority']} (Category: {c_infra['category']})")
assert c_infra['assigned_authority'] == "Estate Office"

c_acad = post("http://127.0.0.1:8000/complaints", {"text": "CS exam marks wrong and not published"})
print(f"Academic Ticket #{c_acad['id']} -> Assigned: {c_acad['assigned_authority']} (Category: {c_acad['category']})")
assert c_acad['assigned_authority'] == "HOD"

c_mess = post("http://127.0.0.1:8000/complaints", {"text": "Mess dining food hygiene and flies in kitchen"})
print(f"Mess Ticket #{c_mess['id']} -> Assigned: {c_mess['assigned_authority']} (Category: {c_mess['category']})")
assert c_mess['assigned_authority'] == "Mess Committee"

c_harass = post("http://127.0.0.1:8000/complaints", {"text": "Senior students ragging juniors in corridor"})
print(f"Harassment Ticket #{c_harass['id']} -> Assigned: {c_harass['assigned_authority']} (Category: {c_harass['category']})")
assert c_harass['assigned_authority'] == "Counseling Cell"

print("\n=== [2/3] Verifying Dispatched Emails in Authority Inboxes ===")
warden_emails = get("http://127.0.0.1:8000/authority/emails?assigned_authority=Warden")
print(f"Warden Inbox count: {len(warden_emails)} | Recipient: {warden_emails[0]['recipient_email']} | Link: {warden_emails[0]['portal_link']}")
assert warden_emails[0]['recipient_email'] == "dlogidth4@gmail.com"

estate_emails = get("http://127.0.0.1:8000/authority/emails?assigned_authority=Estate+Office")
print(f"Estate Office Inbox count: {len(estate_emails)} | Recipient: {estate_emails[0]['recipient_email']} | Link: {estate_emails[0]['portal_link']}")
assert estate_emails[0]['recipient_email'] == "717824v134@kce.ac.in"

hod_emails = get("http://127.0.0.1:8000/authority/emails?assigned_authority=HOD")
print(f"HOD Inbox count: {len(hod_emails)} | Recipient: {hod_emails[0]['recipient_email']} | Link: {hod_emails[0]['portal_link']}")
assert hod_emails[0]['recipient_email'] == "717824v101@kce.ac.in"

mess_emails = get("http://127.0.0.1:8000/authority/emails?assigned_authority=Mess+Committee")
print(f"Mess Inbox count: {len(mess_emails)} | Recipient: {mess_emails[0]['recipient_email']} | Link: {mess_emails[0]['portal_link']}")
assert mess_emails[0]['recipient_email'] == "dlogidth5@gmail.com"

counselor_emails = get("http://127.0.0.1:8000/authority/emails?assigned_authority=Counseling+Cell")
print(f"Counseling Cell Inbox count: {len(counselor_emails)} | Recipient: {counselor_emails[0]['recipient_email']} | Link: {counselor_emails[0]['portal_link']}")
assert counselor_emails[0]['recipient_email'] == "717824v152@kce.ac.in"

print("\n=== [3/3] Testing Authority Login and Resolution ===")
login_res = post("http://127.0.0.1:8000/auth/login", {"username": "warden", "password": "warden123"})
token = login_res["access_token"]
print(f"Logged in as Warden -> User: {login_res['user']['full_name']}")

res_ticket = patch(f"http://127.0.0.1:8000/complaints/{c_hostel['id']}/resolve", {"remarks": "Water motor repaired and overhead tank filled."})
print(f"Resolved Ticket #{res_ticket['id']} -> Status: {res_ticket['status']}")

print("\n=======================================================")
print("[ALL LIVE SERVER FUNCTIONALITY & EMAIL DISPATCHES VERIFIED 100%!]")
print("=======================================================")
