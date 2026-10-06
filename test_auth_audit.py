import sys
import os
import requests
import sqlite3
from werkzeug.security import generate_password_hash

BASE_URL = "http://127.0.0.1:5000"

def run_tests():
    print("=" * 60)
    print("RUNNING AUTOMATED AUTHENTICATION TEST SUITE (12 TESTS)")
    print("=" * 60)

    results = {}

    # TEST 1: Correct username + correct password
    s1 = requests.Session()
    r1 = s1.post(f"{BASE_URL}/auth/login", data={"username": "admin", "password": "admin123"}, allow_redirects=False)
    t1_pass = (r1.status_code == 302 and "dashboard" in r1.headers.get("Location", "") and "session" in s1.cookies)
    results["TEST 1: Correct username + correct password"] = "PASS" if t1_pass else "FAIL"

    # TEST 2: Correct username + wrong password
    s2 = requests.Session()
    r2 = s2.post(f"{BASE_URL}/auth/login", data={"username": "admin", "password": "wrongpassword123"}, allow_redirects=False)
    t2_pass = (r2.status_code == 200 and "Invalid username or password." in r2.text and "session" not in s2.cookies)
    results["TEST 2: Correct username + wrong password"] = "PASS" if t2_pass else "FAIL"

    # TEST 3: Wrong username + password
    s3 = requests.Session()
    r3 = s3.post(f"{BASE_URL}/auth/login", data={"username": "nonexistent_admin_xyz", "password": "admin123"}, allow_redirects=False)
    t3_pass = (r3.status_code == 200 and "Invalid username or password." in r3.text and "session" not in s3.cookies)
    results["TEST 3: Wrong username + password"] = "PASS" if t3_pass else "FAIL"

    # TEST 4: Username with spaces (leading, trailing)
    s4 = requests.Session()
    r4 = s4.post(f"{BASE_URL}/auth/login", data={"username": "  admin  ", "password": "admin123"}, allow_redirects=False)
    t4_pass = (r4.status_code == 302 and "dashboard" in r4.headers.get("Location", ""))
    results["TEST 4: Username with spaces"] = "PASS" if t4_pass else "FAIL"

    # TEST 5: Application restart simulation (verifying credentials and hash consistency)
    from app import create_app
    from models import db, User
    app_instance = create_app()
    with app_instance.app_context():
        admin_user = User.query.filter_by(username="admin").first()
        t5_pass = (admin_user is not None and admin_user.check_password("admin123") and admin_user.is_active)
    results["TEST 5: Application restart (Password persistence)"] = "PASS" if t5_pass else "FAIL"

    # TEST 6: Database restart simulation (direct sqlite3 connection check)
    conn = sqlite3.connect("inventory.db")
    c = conn.cursor()
    c.execute("SELECT id, username, is_active FROM users WHERE username = 'admin'")
    row = c.fetchone()
    conn.close()
    t6_pass = (row is not None and row[1] == "admin" and row[2] == 1)
    results["TEST 6: Database restart (Connection & Record integrity)"] = "PASS" if t6_pass else "FAIL"

    # TEST 7: Password change
    s7 = requests.Session()
    # Log in first
    s7.post(f"{BASE_URL}/auth/login", data={"username": "admin", "password": "admin123"})
    # Change password to new password
    new_pw = "NewAdminPass2026!"
    r7 = s7.post(f"{BASE_URL}/settings/change-password", data={
        "current_password": "admin123",
        "new_password": new_pw,
        "confirm_password": new_pw
    }, allow_redirects=False)
    
    # Try logging in with the NEW password
    s7_verify = requests.Session()
    r7_login = s7_verify.post(f"{BASE_URL}/auth/login", data={"username": "admin", "password": new_pw}, allow_redirects=False)
    t7_pass = (r7_login.status_code == 302 and "dashboard" in r7_login.headers.get("Location", ""))
    results["TEST 7: Password change (New password works)"] = "PASS" if t7_pass else "FAIL"

    # TEST 8: Old password after password change
    s8 = requests.Session()
    r8 = s8.post(f"{BASE_URL}/auth/login", data={"username": "admin", "password": "admin123"}, allow_redirects=False)
    t8_pass = (r8.status_code == 200 and "Invalid username or password." in r8.text)
    results["TEST 8: Old password after change rejected"] = "PASS" if t8_pass else "FAIL"

    # Restore initial admin123 password directly
    conn = sqlite3.connect("inventory.db")
    c = conn.cursor()
    c.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'", (generate_password_hash("admin123"),))
    conn.commit()
    conn.close()

    # TEST 9: Logout clears session
    s9 = requests.Session()
    s9.post(f"{BASE_URL}/auth/login", data={"username": "admin", "password": "admin123"})
    r9_logout = s9.get(f"{BASE_URL}/auth/logout", allow_redirects=False)
    # Check that accessing protected route now fails
    r9_dash = s9.get(f"{BASE_URL}/dashboard/", allow_redirects=False)
    t9_pass = (r9_logout.status_code == 302 and r9_dash.status_code == 302 and "login" in r9_dash.headers.get("Location", ""))
    results["TEST 9: Logout clears session"] = "PASS" if t9_pass else "FAIL"

    # TEST 10: Login redirect
    s10 = requests.Session()
    r10 = s10.post(f"{BASE_URL}/auth/login?next=/settings/", data={"username": "admin", "password": "admin123"}, allow_redirects=False)
    t10_pass = (r10.status_code == 302 and r10.headers.get("Location", "") == "/settings/")
    results["TEST 10: Login redirect with ?next="] = "PASS" if t10_pass else "FAIL"

    # TEST 11: Protected route without login redirects to login
    s11 = requests.Session()
    r11 = s11.get(f"{BASE_URL}/settings/", allow_redirects=False)
    t11_pass = (r11.status_code == 302 and "auth/login" in r11.headers.get("Location", ""))
    results["TEST 11: Protected route without login redirects"] = "PASS" if t11_pass else "FAIL"

    # TEST 12: Verify running application uses the same database
    from config import Config
    db_path = Config.FALLBACK_SQLITE_URI.split("///")[-1]
    same_db = os.path.abspath(db_path) == os.path.abspath("inventory.db") and os.path.exists("inventory.db")
    results["TEST 12: Running app uses single database (inventory.db)"] = "PASS" if same_db else "FAIL"

    print("\n--- TEST SUMMARY ---")
    all_passed = True
    for test_name, status in results.items():
        print(f"[{status}] {test_name}")
        if status != "PASS":
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("ALL 12 TESTS PASSED SUCCESSFULLY!")
    else:
        print("SOME TESTS FAILED.")
    print("=" * 60)
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(run_tests())
