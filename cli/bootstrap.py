import os
import sys
import subprocess


def _ensure_venv():
    """确保虚拟环境存在并激活"""
    _HERE = os.path.dirname(os.path.abspath(__file__))
    venv_dir = os.path.join(_HERE, "..", "venv")

    # 如果已经在虚拟环境中，直接返回
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        return

    # 创建虚拟环境
    if not os.path.exists(venv_dir):
        print("创建虚拟环境...")
        subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
        # Python 3.12+ venv 默认不含 pip，需手动引导
        venv_python = _get_venv_python(venv_dir)
        subprocess.check_call([venv_python, "-m", "ensurepip", "--upgrade"])
        print("✅ 虚拟环境创建完成\n")

    # 重新启动脚本在虚拟环境中
    python_exe = _get_venv_python(venv_dir)

    os.execv(python_exe, [python_exe] + sys.argv)


def _get_venv_python(venv_dir):
    candidates = []
    if sys.platform == "win32":
        candidates.append(os.path.join(venv_dir, "Scripts", "python.exe"))
    else:
        candidates.extend([
            os.path.join(venv_dir, "bin", "python"),
            os.path.join(venv_dir, "bin", "python3"),
        ])

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    raise FileNotFoundError(f"未找到虚拟环境 Python: {venv_dir}")


def _ensure_deps():
    _HERE = os.path.dirname(os.path.abspath(__file__))
    req_file = os.path.join(_HERE, "..", "requirements.txt")
    missing = []
    pkg_map = {
        "camoufox": "camoufox",
        "patchright": "patchright",
        "psutil": "psutil",
        "quart": "quart",
        "requests": "requests",
        "rich": "rich",
    }
    for mod, pkg in pkg_map.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"正在安装依赖: {', '.join(missing)}...")
        # 兜底：确保 pip 可用（Python 3.12+ venv 可能不含 pip）
        try:
            import pip  # noqa: F401
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", "-q"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file, "-q"])
        print("✅ 依赖安装完成\n")


def _camoufox_browser_ready():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "camoufox", "path"],
            capture_output=True,
            check=True,
            text=True,
        )
    except Exception:
        return False

    install_dir = result.stdout.strip()
    if not install_dir:
        return False

    if os.path.isfile(install_dir):
        return True

    if not os.path.isdir(install_dir):
        return False

    try:
        return bool(os.listdir(install_dir))
    except OSError:
        return False


def _default_patchright_browser_root():
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if env_path:
        if env_path == "0":
            import patchright
            return os.path.join(os.path.dirname(patchright.__file__), "driver", "package", ".local-browsers")
        return os.path.expanduser(env_path)

    home = os.path.expanduser("~")
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return os.path.join(local_app_data, "ms-playwright")
        return os.path.join(home, "AppData", "Local", "ms-playwright")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Caches", "ms-playwright")
    return os.path.join(home, ".cache", "ms-playwright")


def _patchright_expected_browser_paths():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "patchright", "install", "--dry-run", "chromium"],
            capture_output=True,
            text=True,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    paths = []
    prefix = "Install location:"
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        install_path = line[len(prefix):].strip()
        if install_path:
            paths.append(install_path)
    return paths


def _patchright_browser_ready():
    expected_paths = _patchright_expected_browser_paths()
    if expected_paths:
        for install_path in expected_paths:
            if os.path.basename(install_path).startswith("chromium-") and os.path.isdir(install_path):
                return True
        return False

    browser_root = _default_patchright_browser_root()
    if not os.path.isdir(browser_root):
        return False

    try:
        entries = os.listdir(browser_root)
    except OSError:
        return False

    for entry in entries:
        if entry.startswith("chromium-"):
            return True
    return False


def _ensure_camoufox_browser():
    if _camoufox_browser_ready():
        return

    print("正在下载 Camoufox 浏览器...")
    subprocess.check_call([sys.executable, "-m", "camoufox", "fetch"])
    print("✅ 浏览器下载完成\n")


def _ensure_patchright_browser():
    if _patchright_browser_ready():
        return

    print("正在安装 Patchright 浏览器...")
    if sys.platform.startswith("linux"):
        try:
            subprocess.check_call([sys.executable, "-m", "patchright", "install", "--with-deps", "chromium"])
        except subprocess.CalledProcessError:
            print("⚠️  Patchright --with-deps 安装失败，尝试退回普通安装 chromium...")
            subprocess.check_call([sys.executable, "-m", "patchright", "install", "chromium"])
    else:
        subprocess.check_call([sys.executable, "-m", "patchright", "install", "chromium"])
    print("✅ Patchright 浏览器安装完成\n")


def _ensure_service_browsers(service):
    if service == "you":
        _ensure_patchright_browser()
    else:
        _ensure_camoufox_browser()
        if service == "tavily":
            _ensure_patchright_browser()
