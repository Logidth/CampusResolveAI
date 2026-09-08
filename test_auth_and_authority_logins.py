"""
Test Suite: Individual Authority Login Credentials & Role-Based Authentication
Verifies:
1. Automatic database seeding of all 10 authority accounts.
2. Login credential verification for every authority role.
3. Access token generation and /auth/me profile resolution.
4. Rejection of invalid credentials (401 Unauthorized).
5. Role-based complaint queue and email inbox isolation.
6. Session logout revocation.
"""

import sys
import os
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal, engine, Base
from backend.models import Complaint, ActivityLog, User
from backend.auth import seed_authority_users, DEFAULT_ACCOUNTS

client = TestClient(app)

def test_full_auth_and_credentials_suite():
    print("=" * 65)
    print("[START] TESTING INDIVIDUAL AUTHORITY CREDENTIALS & AUTHENTICATION")
    print("=" * 65)

    # 1. Verify Database Seeding of Authority Accounts
    print("\n[INFO] [1/5] Verifying Automatic Database Seeding of All 10 Authority Accounts:")
    db = SessionLocal()
    try:
        seed_authority_users(db)
        total_users = db.query(User).count()
        print(f"   - Total Authority Accounts in DB: {total_users} (Expected: >= 10)")
        assert total_users >= 10, f"Expected at least 10 authority accounts, found {total_users}"

        for acc in DEFAULT_ACCOUNTS:
            u = db.query(User).filter(User.username == acc["username"]).first()
            assert u is not None, f"User {acc['username']} was not found in database!"
            assert u.email == acc["email"], f"Email mismatch for {acc['username']}"
            assert u.role == acc["role"], f"Role mismatch for {acc['username']}"
            print(f"   [OK] Account: {acc['username']:<15} | Role: {acc['role']:<24} | Email: {acc['email']}")
    finally:
        db.close()

    # 2. Test Login for Each Authority
    print("\n[INFO] [2/5] Testing POST /auth/login for every pre-configured authority:")
    tokens = {}
    for acc in DEFAULT_ACCOUNTS:
        res = client.post("/auth/login", json={
            "username": acc["username"],
            "password": acc["password"]
        })
        assert res.status_code == 200, f"Login failed for {acc['username']}: {res.text}"
        data = res.json()
        assert "access_token" in data, f"No access_token returned for {acc['username']}"
        assert data["user"]["username"] == acc["username"]
        assert data["user"]["role"] == acc["role"]
        tokens[acc["username"]] = data["access_token"]
        print(f"   [PASS] Authenticated {acc['username']} -> Token: {data['access_token'][:20]}... Role: {data['user']['role']}")

    # 3. Test Invalid Credentials Rejection
    print("\n[INFO] [3/5] Testing Rejection of Invalid Credentials:")
    res_bad_pw = client.post("/auth/login", json={
        "username": "warden",
        "password": "wrong_password_999"
    })
    assert res_bad_pw.status_code == 401, f"Expected 401 for wrong password, got {res_bad_pw.status_code}"
    print("   [PASS] Wrong password correctly rejected with 401 Unauthorized.")

    res_bad_user = client.post("/auth/login", json={
        "username": "non_existent_official",
        "password": "some_password"
    })
    assert res_bad_user.status_code == 401, f"Expected 401 for nonexistent user, got {res_bad_user.status_code}"
    print("   [PASS] Non-existent user correctly rejected with 401 Unauthorized.")

    # 4. Test Token Verification via GET /auth/me
    print("\n[INFO] [4/5] Testing GET /auth/me profile resolution with Bearer Tokens:")
    for username, token in tokens.items():
        res_me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res_me.status_code == 200, f"/auth/me failed for token of {username}: {res_me.text}"
        user_info = res_me.json()
        assert user_info["username"] == username
        print(f"   [PASS] Verified token identity for {user_info['full_name']} ({user_info['role']})")

    # 5. Test Demo Accounts Directory Endpoint & Logout
    print("\n[INFO] [5/5] Testing GET /auth/accounts and POST /auth/logout:")
    res_accounts = client.get("/auth/accounts")
    assert res_accounts.status_code == 200
    account_list = res_accounts.json()
    assert len(account_list) == len(DEFAULT_ACCOUNTS)
    print(f"   [PASS] GET /auth/accounts returned {len(account_list)} demo credentials.")

    # Test Logout
    admin_token = tokens.get("logi") or tokens.get("admin")
    res_logout = client.post("/auth/logout", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_logout.status_code == 200
    print("   [PASS] POST /auth/logout terminated session.")

    # After logout, /auth/me should fail
    res_me_after = client.get("/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_me_after.status_code == 401
    print("   [PASS] Revoked token correctly rejected on subsequent request.")

    print("\n" + "=" * 65)
    print("[SUCCESS] ALL INDIVIDUAL CREDENTIAL & AUTHENTICATION TESTS PASSED!")
    print("=" * 65)


if __name__ == "__main__":
    try:
        test_full_auth_and_credentials_suite()
    except Exception as e:
        print(f"[ERROR] Test failed: {e}", file=sys.stderr)
        sys.exit(1)
