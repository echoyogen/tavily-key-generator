import time


def detect_signup_result(page, signup_events):
    snapshots = []
    current_url = page.url.lower()

    if "confirm-email" in current_url or "confirm_email" in current_url:
        return ("sent", "")

    try:
        snapshots.append(page.locator("body").inner_text())
    except Exception:
        pass

    try:
        snapshots.append(page.content())
    except Exception:
        pass

    snapshots.extend(event.get("body", "") for event in signup_events[-6:])
    combined = "\n".join(snapshots).lower()

    if "security check failed" in combined or "suspicious activity" in combined:
        return (
            "blocked",
            "Firecrawl returned Security check failed / suspicious activity, current browser fingerprint or network is blocked.",
        )

    if "already exists" in combined or "account already exists" in combined:
        return ("exists", "This email appears to already be registered.")

    if "invalid email" in combined or "email address is invalid" in combined:
        return ("invalid_email", "The service considers this email address invalid.")

    if "password is not strong enough" in combined or "at least 12 characters" in combined:
        return (
            "weak_password",
            "The service rejected the password strength, requires at least 12 characters with upper/lower case, digits and special characters.",
        )

    success_markers = (
        "check your email",
        "confirm email",
        "confirmation link",
        "verify your email",
        "verification email",
        "email has been sent",
        "we sent you an email",
        "did not receive the email",
        "once confirmed, you may sign in",
    )
    if any(marker in combined for marker in success_markers):
        return ("sent", "")

    return ("", "")


def wait_for_signup_result(page, signup_events, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, message = detect_signup_result(page, signup_events)
        if status:
            return status, message
        time.sleep(1)

    current_url = page.url.lower()
    if "confirm-email" in current_url or "confirm_email" in current_url:
        return ("sent", "")

    if "view=signup" in current_url or current_url.rstrip("/").endswith("/signin"):
        return (
            "stalled",
            "Page remained on signup after submission, no confirmation that verification email was sent.",
        )

    return ("", "")
