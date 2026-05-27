from mail_provider import create_email
from you_browser_solver import register_with_browser


def register(email, password):
    return register_with_browser(email, password)


if __name__ == "__main__":
    email, password = create_email(service="you")
    result = register(email, password)
    if result:
        print(f"Registration successful: {email}")
    else:
        print(f"Registration failed: {email}")
