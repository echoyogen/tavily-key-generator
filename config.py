"""
Tavily 注册器配置
优先读取环境变量；若项目根目录存在 .env，则先载入。
"""
import os
from pathlib import Path

PLACEHOLDER_ENV_VALUES = {
    "SERVER_URL": {"https://your-server.example.com"},
    "SERVER_ADMIN_PASSWORD": {"replace-with-your-admin-password"},
}


def _load_dotenv():
    env_path = Path(__file__).resolve().with_name(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _get_str(name, default=""):
    return os.getenv(name, default).strip()


def _get_int(name, default):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)

def _get_list(name, fallback=""):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        value = fallback
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_placeholder_env_value(name, value):
    normalized = (value or "").strip()
    if not normalized:
        return False

    normalized_lower = normalized.lower()
    placeholder_values = {item.lower() for item in PLACEHOLDER_ENV_VALUES.get(name, set())}
    if normalized_lower in placeholder_values:
        return True

    if normalized_lower.startswith("replace-with-"):
        return True

    if normalized_lower in {"example.com", "example.org"}:
        return True

    if normalized_lower.startswith("https://your-") and ".example.com" in normalized_lower:
        return True

    return False


_load_dotenv()

# 上传目标
SERVER_URL = _get_str("SERVER_URL")
SERVER_ADMIN_PASSWORD = _get_str("SERVER_ADMIN_PASSWORD")

# 注册默认参数
DEFAULT_COUNT = _get_int("DEFAULT_COUNT", 5)
DEFAULT_CONCURRENCY = _get_int("DEFAULT_CONCURRENCY", 2)
DEFAULT_DELAY = _get_int("DEFAULT_DELAY", 10)
DEFAULT_UPLOAD = _get_bool("DEFAULT_UPLOAD", True)

# 浏览器模式
REGISTER_HEADLESS = _get_bool("REGISTER_HEADLESS", True)
# Firecrawl 未单独配置时，默认继承 REGISTER_HEADLESS，避免意外跑到前台。
FIRECRAWL_REGISTER_HEADLESS = _get_bool("FIRECRAWL_REGISTER_HEADLESS", REGISTER_HEADLESS)
YOU_REGISTER_HEADLESS = _get_bool("YOU_REGISTER_HEADLESS", REGISTER_HEADLESS)
SERPER_REGISTER_HEADLESS = _get_bool("SERPER_REGISTER_HEADLESS", REGISTER_HEADLESS)
VALYU_REGISTER_HEADLESS = _get_bool("VALYU_REGISTER_HEADLESS", REGISTER_HEADLESS)
EMAIL_CODE_TIMEOUT = _get_int("EMAIL_CODE_TIMEOUT", 90)
API_KEY_TIMEOUT = _get_int("API_KEY_TIMEOUT", 20)
EMAIL_POLL_INTERVAL = _get_int("EMAIL_POLL_INTERVAL", 3)

# Solver 配置
SOLVER_PORT = _get_str("SOLVER_PORT", "5073")
LOCAL_SOLVER_URL = _get_str("LOCAL_SOLVER_URL", f"http://127.0.0.1:{SOLVER_PORT}")
SOLVER_THREADS = _get_int("SOLVER_THREADS", 1)

# 代理配置
PROXY_ENABLED = _get_bool("PROXY_ENABLED", False)
PROXY_LIST = _get_list("PROXY_LIST")

# Web 管理服务配置
WEB_ADMIN_USER = _get_str("WEB_ADMIN_USER", "admin")
WEB_ADMIN_PASSWORD = _get_str("WEB_ADMIN_PASSWORD", "changeme")
WEB_SECRET_KEY = _get_str("WEB_SECRET_KEY", "change-this-to-a-random-secret-string")
WEB_PORT = _get_int("WEB_PORT", 8086)

# 数据库配置
DB_TYPE = _get_str("DB_TYPE", "sqlite").lower()          # "sqlite" | "postgresql"
DB_PATH = _get_str("DB_PATH", "web/data.db")             # SQLite 文件路径
DB_URL = _get_str("DB_URL", "")                          # PostgreSQL 连接 URL

# 邮箱提供商配置
EMAIL_PROVIDER = _get_str("EMAIL_PROVIDER", "cloudflare")  # "cloudflare" | "duckmail" | "onlinemail"
SUPPORTED_EMAIL_PROVIDERS = ["cloudflare", "duckmail", "onlinemail"]

# Cloudflare Email API 配置
EMAIL_API_URL = _get_str("EMAIL_API_URL", "")
EMAIL_API_TOKEN = _get_str("EMAIL_API_TOKEN", "")
EMAIL_DOMAINS = _get_list("EMAIL_DOMAINS")

# DuckMail 配置
DUCKMAIL_API_KEY = _get_str("DUCKMAIL_API_KEY", "")
DUCKMAIL_API_URL = _get_str("DUCKMAIL_API_URL", "https://www.duckmail.de/api/")
DUCKMAIL_DOMAINS = _get_list("DUCKMAIL_DOMAINS", "duckmail.de")

# OnlineMail 配置
ONLINEMAIL_MODE = _get_str("ONLINEMAIL_MODE", "api")  # "api" | "browser"
ONLINEMAIL_API_KEY = _get_str("ONLINEMAIL_API_KEY", "")
ONLINEMAIL_ORDERS_FILE = _get_str("ONLINEMAIL_ORDERS_FILE", "onlinemail_orders.json")
