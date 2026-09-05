from backend.agent import classify_complaint

cases = [
    ('c101 bench is broken', 'infrastructure', 'Estate Office'),
    ('campus , room c405 is not closed', 'infrastructure', 'Estate Office'),
    ('fan in class 201 is making noise', 'infrastructure', 'Estate Office'),
    ('projector in CS lab not working', 'infrastructure', 'Estate Office'),
    ('lift stuck on 3rd floor in main building', 'infrastructure', 'Estate Office'),
    ('H-block water supply is insufficient', 'hostel', 'Warden'),
    ('hostel room 302 geyser not heating', 'hostel', 'Warden'),
    ('warden not allowing gate pass', 'hostel', 'Warden'),
    ('mess food has insects and is cold', 'mess', 'Mess Committee'),
    ('canteen lunch quality is poor', 'mess', 'Mess Committee'),
    ('CS201 exam grading mistake', 'academic', 'HOD'),
    ('faculty did not take class today', 'academic', 'HOD'),
    ('Senior students ragging juniors in corridor', 'harassment', 'Counseling Cell')
]

auth_map = {
    'hostel': 'Warden',
    'mess': 'Mess Committee',
    'academic': 'HOD',
    'infrastructure': 'Estate Office',
    'harassment': 'Counseling Cell'
}

all_pass = True
for text, exp_cat, exp_auth in cases:
    res = classify_complaint(text)
    actual_auth = auth_map.get(res['category'])
    passed = (res['category'] == exp_cat and actual_auth == exp_auth)
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] '{text}' -> {res['category']} ({actual_auth}) [Expected: {exp_cat} ({exp_auth})]")
    if not passed:
        all_pass = False

assert all_pass, "Some classification tests failed!"
print("\n=== ALL 13 TEST CASES PASSED WITH 100% ACCURACY! ===")
