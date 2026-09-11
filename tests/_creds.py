"""Test credentials loader: reads the local admin test account from /app/memory/test_credentials.md
(never hard-code credentials in test sources). Override with TEST_ADMIN_EMAIL / TEST_ADMIN_PASSWORD."""
import os


def admin_credentials():
    email, password = os.environ.get("TEST_ADMIN_EMAIL"), os.environ.get("TEST_ADMIN_PASSWORD")
    if email and password:
        return {"email": email, "password": password}
    creds = {}
    try:
        for line in open("/app/memory/test_credentials.md"):
            if "email" in line.lower() and "@" in line and "email" not in creds:
                creds["email"] = line.split(":")[-1].strip().strip("`* ")
            if "password" in line.lower() and "password" not in creds and ":" in line:
                creds["password"] = line.split(":", 1)[-1].strip().strip("`* ")
    except FileNotFoundError:
        pass
    return creds
