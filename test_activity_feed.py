import os
os.environ['MOCK_MODE'] = 'true'

from datetime import datetime
from fastapi.testclient import TestClient
from backend.main import app
from backend.scheduler import check_and_escalate_grievances
from backend.database import SessionLocal, engine, Base
from backend.models import Complaint, ActivityLog

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

print("=" * 65)
print("[START] TESTING GET /activity-feed & WEBSOCKET /ws/activity")
print("=" * 65)

with TestClient(app) as client:
    # 1. Establish WebSocket Connection
    with client.websocket_connect("/ws/activity") as websocket:
        print("[PASS] [1/4] WebSocket connected successfully to /ws/activity")

        # 2. Trigger Complaint Creation (Should push event to WebSocket)
        long_text = "The air conditioning unit and projector in Block D Room 402 are severely malfunctioning and producing smoke"
        res_post = client.post("/complaints", json={"text": long_text})
        assert res_post.status_code == 201
        c_data = res_post.json()
        cid = c_data["id"]

        # Receive WebSocket message for CREATION / CLASSIFICATION
        ws_msg1 = websocket.receive_json()
        print(f"\n[PASS] [2/4] Real-time WebSocket event received on Creation:")
        print(f"   - Action: {ws_msg1['action']}")
        print(f"   - Complaint ID: {ws_msg1['complaint_id']}")
        print(f"   - Truncated Text: '{ws_msg1['complaint_text']}' (len: {len(ws_msg1['complaint_text'])})")
        print(f"   - Status: {ws_msg1['complaint_status']}")
        
        assert ws_msg1["complaint_id"] == cid
        assert ws_msg1["action"] == "CLASSIFICATION"
        assert len(ws_msg1["complaint_text"]) <= 63 # 60 chars + '...'
        assert ws_msg1["complaint_text"].endswith("...")
        assert ws_msg1["complaint_status"] == "open"

        # 3. Trigger Complaint Resolution (Should push event to WebSocket)
        res_res = client.patch(f"/complaints/{cid}/resolve")
        assert res_res.status_code == 200

        ws_msg2 = websocket.receive_json()
        print(f"\n[PASS] [3/4] Real-time WebSocket event received on Resolve:")
        print(f"   - Action: {ws_msg2['action']}")
        print(f"   - Details: {ws_msg2['details']}")
        print(f"   - Status: {ws_msg2['complaint_status']}")
        assert ws_msg2["action"] == "RESOLVED"
        assert ws_msg2["complaint_status"] == "resolved"

    # 4. Test GET /activity-feed endpoint
    res_feed = client.get("/activity-feed")
    assert res_feed.status_code == 200
    feed = res_feed.json()
    print(f"\n[PASS] [4/4] GET /activity-feed returned {len(feed)} entries:")
    for item in feed:
        print(f"   - [{item['action']}] Ticket #{item['complaint_id']} | Text: '{item['complaint_text']}' | Status: {item['complaint_status']}")

    assert len(feed) == 2
    # Newest first: RESOLVED should be first, CLASSIFICATION second
    assert feed[0]["action"] == "RESOLVED"
    assert feed[1]["action"] == "CLASSIFICATION"
    assert "complaint_text" in feed[0]
    assert "complaint_status" in feed[0]

print("\n" + "=" * 65)
print("[SUCCESS] ALL ACTIVITY FEED & WEBSOCKET REAL-TIME TESTS PASSED!")
print("=" * 65)
