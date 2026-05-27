"""
valyu.ai 注册统一入口
"""
from mail_provider import create_email
from valyu_browser_solver import register_with_browser


def register(email, password):
    return register_with_browser(email, password)


if __name__ == "__main__":
    email, password = create_email(service="valyu")
    result = register(email, password)
    if result:
        print(f"✅ 注册成功: {email}")
    else:
        print(f"❌ 注册失败: {email}")
