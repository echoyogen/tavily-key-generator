import os
import sys
import signal
import subprocess
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import requests as std_requests

from config import (
    SERVER_URL,
    SERVER_ADMIN_PASSWORD,
    SOLVER_PORT,
    SOLVER_THREADS,
    LOCAL_SOLVER_URL,
)

solver_proc = None


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


def start_solver(thread_count=None):
    global solver_proc
    actual_threads = max(SOLVER_THREADS, thread_count or 1)

    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline') or []
                if any('api_solver.py' in str(c) for c in cmdline):
                    print(f"清理旧 Solver 进程 (PID: {proc.pid})")
                    proc.kill()
                    time.sleep(1)
            except:
                pass
    except ImportError:
        print("⚠️  未安装 psutil，跳过旧 Solver 进程清理")

    print(f"启动 Turnstile Solver... (threads={actual_threads})")

    if os.path.exists('venv'):
        python_path = _get_venv_python('venv')
    else:
        python_path = sys.executable

    solver_proc = subprocess.Popen(
        [python_path, 'api_solver.py', '--browser_type', 'chromium', '--thread', str(actual_threads), '--port', SOLVER_PORT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    for i in range(30):
        try:
            r = std_requests.get(f"{LOCAL_SOLVER_URL}/", timeout=1)
            if r.status_code == 200:
                print("✅ Solver 已启动\n")
                return True
        except:
            pass
        time.sleep(1)
        if i % 5 == 0:
            print(f"等待 Solver 启动... ({i}s)")

    print("❌ Solver 启动超时")
    return False


def stop_solver():
    global solver_proc
    if solver_proc:
        solver_proc.terminate()
        try:
            solver_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            solver_proc.kill()
            solver_proc.wait(timeout=5)
        solver_proc = None


def signal_handler(sig, frame):
    print("\n\n正在退出...")
    stop_solver()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, signal_handler)


def upload_key(email, api_key, service="tavily"):
    try:
        r = std_requests.post(
            f"{SERVER_URL}/api/keys",
            json={"key": api_key, "email": email, "service": service},
            headers={"Authorization": f"Bearer {SERVER_ADMIN_PASSWORD}"},
            timeout=15,
        )
        if r.status_code in (200, 201):
            print("✅ 已上传服务器")
            return True
        print(f"⚠️  上传失败 {r.status_code}: {r.text[:100]}")
        return False
    except Exception as e:
        print(f"⚠️  上传失败: {e}")
        return False


def register_one(index, total, upload, service="tavily"):
    print(f"{'='*60}")
    print(f"📧 注册 ({index}/{total})")
    print(f"{'='*60}\n")

    try:
        from services.registry import get_service
        from mail.factory import create_email

        email, password = create_email(service=service)
        svc = get_service(service)
        result = svc.register(email, password)

        if result and result != "SUCCESS_NO_KEY":
            if upload:
                upload_key(email, result, service=service)
            return "success"
        if result == "SUCCESS_NO_KEY":
            return "success_no_key"
        return "failed"
    except Exception as e:
        print(f"❌ 注册异常: {e}")
        return "failed"


def do_register_parallel(count, delay, upload, concurrency, service="tavily"):
    success = 0
    failed = 0
    actual_concurrency = max(1, min(concurrency, count))
    print(f"⚙️  本轮并发: {actual_concurrency}")

    if actual_concurrency == 1:
        for i in range(count):
            if i > 0:
                print(f"\n⏳ 等待 {delay} 秒...\n")
                time.sleep(delay)
            status = register_one(i + 1, count, upload, service)
            if status in {"success", "success_no_key"}:
                success += 1
            else:
                failed += 1
    else:
        print("🧵 已启用并发注册模式")
        with ThreadPoolExecutor(max_workers=actual_concurrency) as executor:
            futures = {}
            next_index = 1

            while next_index <= count and len(futures) < actual_concurrency:
                future = executor.submit(register_one, next_index, count, upload, service)
                futures[future] = next_index
                next_index += 1

            while futures:
                done, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)
                for future in done:
                    futures.pop(future, None)
                    status = future.result()
                    if status in {"success", "success_no_key"}:
                        success += 1
                    else:
                        failed += 1

                    if next_index <= count:
                        if delay > 0:
                            print(f"\n⏳ 等待 {delay} 秒后补充新任务...\n")
                            time.sleep(delay)
                        next_future = executor.submit(register_one, next_index, count, upload, service)
                        futures[next_future] = next_index
                        next_index += 1

    print(f"\n{'='*60}")
    print(f"✅ 成功: {success}  ❌ 失败: {failed}")
    print(f"{'='*60}\n")


def run_register_flow(count, delay, upload, concurrency, service="tavily"):
    if count <= 0:
        print("❌ 注册数量必须大于 0")
        return
    if delay < 0:
        print("❌ 间隔秒数不能小于 0")
        return
    if concurrency <= 0:
        print("❌ 并发数必须大于 0")
        return
    print(f"\n🚀 开始注册: 数量={count} 并发={min(concurrency, count)} 间隔={delay}s 上传={'是' if upload else '否'}")
    do_register_parallel(count, delay, upload, concurrency, service)
