from config import (
    DEFAULT_UPLOAD,
    DEFAULT_CONCURRENCY,
    DUCKMAIL_API_KEY,
    DUCKMAIL_API_URL,
    DUCKMAIL_DOMAINS,
    EMAIL_PROVIDER,
    SERVER_URL,
    SERVER_ADMIN_PASSWORD,
    EMAIL_API_URL,
    EMAIL_API_TOKEN,
    EMAIL_DOMAINS,
    SUPPORTED_EMAIL_PROVIDERS,
    DEFAULT_COUNT,
    DEFAULT_DELAY,
    is_placeholder_env_value,
    SOLVER_PORT,
    ONLINEMAIL_MODE,
    ONLINEMAIL_API_KEY,
    ONLINEMAIL_ORDERS_FILE,
)



def prompt_service_choice():
    from services.registry import list_services, get_service
    services = list_services()
    print("\n请选择要注册的服务：")
    for index, key in enumerate(services, start=1):
        svc = get_service(key)
        print(f"  {index}. {str(svc.name).capitalize()}")

    while True:
        print(f"请输入选项 (1-{len(services)}，默认 1): ", end="")
        raw = input().strip()
        if raw == "" or raw == "1":
            return services[0]
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(services):
                return services[choice - 1]
        print("❌ 请输入有效编号")


def print_runtime_summary(service="tavily"):
    from services.registry import get_service
    svc = get_service(service)
    service_name = str(svc.name).capitalize()
    output_file = svc.output_file
    account_prefix = svc.api_key_prefix
    print(f"""
┌──────────────────────────────────────────┐
│      多服务自动注册启动台                │
├──────────────────────────────────────────┤
│  当前服务: {service_name:<10}               │
│  自动检查环境 / 依赖 / 邮箱配置             │
└──────────────────────────────────────────┘
""")
    print("当前默认配置：")
    print(f"  账号前缀: {account_prefix}")
    print(f"  输出文件: {output_file}")
    print(f"  邮箱链路: {EMAIL_PROVIDER}")
    print(f"  注册间隔: {DEFAULT_DELAY}s")
    print(f"  默认并发: {DEFAULT_CONCURRENCY}")
    print(f"  默认上传: {'开启' if DEFAULT_UPLOAD else '关闭'}")
    if service == "tavily":
        print(f"  Solver 端口: {SOLVER_PORT}")





def prompt_register_count():
    while True:
        print(f"\n请输入注册数量 (默认 {DEFAULT_COUNT}): ", end="")
        raw = input().strip()
        if raw == "":
            return DEFAULT_COUNT
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("❌ 请输入大于 0 的整数")


def prompt_concurrency(count):
    default_concurrency = min(DEFAULT_CONCURRENCY, count)
    while True:
        print(f"请输入并发数 (默认 {default_concurrency}): ", end="")
        raw = input().strip()
        if raw == "":
            return default_concurrency
        if raw.isdigit():
            value = int(raw)
            if value > 0:
                return min(value, count)
        print("❌ 请输入大于 0 的整数")


def prompt_upload_choice():
    default_label = "Y/n" if DEFAULT_UPLOAD else "y/N"
    while True:
        print(f"是否自动上传到服务器? [{default_label}]: ", end="")
        raw = input().strip().lower()
        if raw == "":
            return DEFAULT_UPLOAD
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("❌ 请输入 y 或 n")


def validate_runtime_config(upload, show_provider_summary=True):
    if EMAIL_PROVIDER not in SUPPORTED_EMAIL_PROVIDERS:
        print(f"❌ 不支持的 EMAIL_PROVIDER: {EMAIL_PROVIDER}")
        print(f"   当前仅支持: {', '.join(SUPPORTED_EMAIL_PROVIDERS)}")
        return False

    missing = []
    placeholder = []
    required = {}

    def append_unique(items, value):
        if value not in items:
            items.append(value)

    if EMAIL_PROVIDER == "duckmail":
        required["DUCKMAIL_API_URL"] = DUCKMAIL_API_URL
        if any(is_placeholder_env_value("DUCKMAIL_DOMAINS", item) for item in DUCKMAIL_DOMAINS):
            append_unique(placeholder, "DUCKMAIL_DOMAIN / DUCKMAIL_DOMAINS")
    elif EMAIL_PROVIDER == "onlinemail":
        if ONLINEMAIL_MODE == "api":
            if not ONLINEMAIL_API_KEY:
                missing.append("ONLINEMAIL_API_KEY")
        else:
            if not ONLINEMAIL_ORDERS_FILE:
                missing.append("ONLINEMAIL_ORDERS_FILE")
    else:
        required.update({
            "EMAIL_API_URL": EMAIL_API_URL,
            "EMAIL_API_TOKEN": EMAIL_API_TOKEN,
        })
        if not EMAIL_DOMAINS:
            missing.append("EMAIL_DOMAIN / EMAIL_DOMAINS")
        elif any(is_placeholder_env_value("EMAIL_DOMAINS", item) for item in EMAIL_DOMAINS):
            append_unique(placeholder, "EMAIL_DOMAIN / EMAIL_DOMAINS")

    if upload:
        required.update({
            "SERVER_URL": SERVER_URL,
            "SERVER_ADMIN_PASSWORD": SERVER_ADMIN_PASSWORD,
        })

    for key, value in required.items():
        if not value:
            missing.append(key)
        elif is_placeholder_env_value(key, value):
            append_unique(placeholder, key)

    if missing or placeholder:
        if missing:
            print("❌ 缺少必要环境变量/配置：")
        for key in missing:
            print(f"   - {key}")
        if placeholder:
            print("❌ 检测到 .env.example 占位值尚未替换：")
            for key in placeholder:
                print(f"   - {key}")
        print("   请先配置 .env 或系统环境变量，并把示例占位值替换成真实配置。")
        return False

    if show_provider_summary:
        if EMAIL_PROVIDER == "duckmail":
            configured = ", ".join(DUCKMAIL_DOMAINS) if DUCKMAIL_DOMAINS else "未配置，启动时自动选择"
            api_hint = "已配置 API Key" if DUCKMAIL_API_KEY else "未配置 API Key（仅可使用公开域名）"
            print(f"📧 当前邮箱 provider: duckmail")
            print(f"   域名配置: {configured}")
            print(f"   API: {api_hint}")
        elif EMAIL_PROVIDER == "onlinemail":
            mode_hint = f"mode={ONLINEMAIL_MODE}"
            if ONLINEMAIL_MODE == "file":
                mode_hint += f", file={ONLINEMAIL_ORDERS_FILE}"
            print(f"📧 当前邮箱 provider: onlinemail ({mode_hint})")
        else:
            print(f"📧 当前邮箱 provider: cloudflare")
            print(f"   域名配置: {', '.join(EMAIL_DOMAINS)}")

    return True
