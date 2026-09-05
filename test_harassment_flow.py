import os
from datetime import datetime, timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.agent import classify_complaint
from backend.scheduler import check_and_escalate_grievances
from backend.database import SessionLocal, engine, Base
from backend.models import Complaint, ActivityLog

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

print("=" * 65)
print("[START] VERIFYING HARASSMENT SAFETY, PRIVACY & API ERROR HANDLING")
print("=" * 65)

with TestClient(app) as client:
    # --- 1. TEST API ERROR HANDLING & TIMEOUT FALLBACK ---
    print("\n[INFO] [1/4] Testing API Error Handling & Timeout Fallback in agent.py:")
    
    # Simulate API failure / timeout in Groq/Claude call
    with patch("backend.agent.GROQ_API_KEY", "dummy_key"):
        with patch("backend.agent.MOCK_MODE", False):
            with patch("groq.Groq") as mock_groq:
                mock_groq.side_effect = TimeoutError("Simulated LLM Gateway Timeout 504")
                
                # classify_complaint should NOT crash; it should catch exception and fallback
                result = classify_complaint("Severe water leakage in hostel block 202")
                print(f"   - Handled TimeoutError gracefully -> Result: {result}")
                assert "category" in result
                assert "urgency" in result
                assert "reasoning" in result
                assert result["category"] in ["hostel", "infrastructure"]

    print("[PASS] agent.py error handling & timeout fallback confirmed.")

    # --- 2. TEST HARASSMENT CLASSIFICATION SAFETY ---
    print("\n[INFO] [2/4] Testing Harassment Classification & Safety Rules:")
    res_harass = client.post("/complaints", json={
        "text": "A student is being stalked, harassed, and threatened in the library corridor"
    })
    assert res_harass.status_code == 201
    h_data = res_harass.json()
    hid = h_data["id"]

    print(f"   - Category: {h_data['category']} (Expected: 'harassment')")
    print(f"   - Urgency: {h_data['urgency']} (Expected: 'high')")
    print(f"   - Assigned Authority: {h_data['assigned_authority']} (Expected: 'Counseling Cell')")
    print(f"   - No Auto-Escalation: {h_data['no_auto_escalation']} (Expected: True)")
    
    assert h_data["category"] == "harassment"
    assert h_data["urgency"] == "high"
    assert h_data["assigned_authority"] == "Counseling Cell"
    assert h_data["no_auto_escalation"] is True

    # Seed a normal infrastructure complaint for comparison
    res_infra = client.post("/complaints", json={
        "text": "Broken laboratory exhaust fan in science building"
    })
    assert res_infra.status_code == 201
    iid = res_infra.json()["id"]

    # --- 3. TEST SCHEDULER IMMUNITY ---
    print("\n[INFO] [3/4] Testing Scheduler Auto-Escalation Immunity:")
    db = SessionLocal()
    # Simulate expired SLAs
    for c in db.query(Complaint).all():
        c.sla_deadline = datetime.utcnow() - timedelta(hours=20)
    db.commit()

    check_and_escalate_grievances(db)

    h_db = db.query(Complaint).filter(Complaint.id == hid).first()
    i_db = db.query(Complaint).filter(Complaint.id == iid).first()

    print(f"   - Harassment Ticket #{hid}: Escalation Level = {h_db.escalation_level} (IMMUNE - Untouched)")
    print(f"   - Infra Ticket #{iid}: Escalation Level = {i_db.escalation_level} (Escalated)")
    assert h_db.escalation_level == 0
    assert h_db.assigned_authority == "Counseling Cell"
    assert i_db.escalation_level == 1
    db.close()
    print("[PASS] Scheduler harassment immunity confirmed.")

    # --- 4. TEST PRIVACY & ENDPOINT ISOLATION ---
    print("\n[INFO] [4/4] Testing Public Dashboard Privacy vs Protected Counselor View:")
    
    # A. Public / General GET /complaints (Should NOT contain harassment)
    res_public = client.get("/complaints")
    assert res_public.status_code == 200
    public_items = res_public.json()
    print(f"   - Public GET /complaints returned {len(public_items)} items:")
    for item in public_items:
        print(f"      - ID #{item['id']} | Category: {item['category']}")
        assert item["category"] != "harassment", f"Privacy Leak: Harassment complaint #{item['id']} exposed in public list!"

    # B. Protected GET /counselor/complaints (Should contain harassment records)
    res_counselor = client.get("/counselor/complaints")
    assert res_counselor.status_code == 200
    counselor_items = res_counselor.json()
    print(f"   - Protected GET /counselor/complaints returned {len(counselor_items)} confidential items:")
    assert len(counselor_items) == 1
    assert counselor_items[0]["id"] == hid
    assert counselor_items[0]["category"] == "harassment"
    print(f"      - Confidential Case #CASE-{counselor_items[0]['id']} securely retrieved for Counselor Cell.")

    # C. Public Activity Feed (Should mask harassment text)
    res_feed = client.get("/activity-feed")
    assert res_feed.status_code == 200
    feed_items = res_feed.json()
    for f in feed_items:
        if f["complaint_id"] == hid:
            print(f"   - Public activity feed masked sensitive text to: '{f['complaint_text']}'")
            assert f["complaint_text"] == "[CONFIDENTIAL - ROUTED TO COUNSELING CELL]"

print("\n" + "=" * 65)
print("[SUCCESS] ALL HARASSMENT SAFETY, PRIVACY & ERROR HANDLING TESTS PASSED!")
print("=" * 65)
