#!/usr/bin/env python3
from cli.bootstrap import _ensure_venv, _ensure_deps
_ensure_venv()
_ensure_deps()

from cli.bootstrap import _ensure_service_browsers
from cli.prompts import (
    prompt_service_choice,
    prompt_register_count, prompt_concurrency,
    prompt_upload_choice, validate_runtime_config,
    print_runtime_summary,
)
from cli.orchestrator import run_register_flow, start_solver, stop_solver, signal_handler

import signal

signal.signal(signal.SIGINT, signal_handler)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, signal_handler)


def main():
    service = prompt_service_choice()
    print_runtime_summary(service)
    need_solver = (service == "tavily")
    if not validate_runtime_config(False, show_provider_summary=True):
        return

    count = prompt_register_count()
    concurrency = prompt_concurrency(count)
    upload = prompt_upload_choice()
    if upload and not validate_runtime_config(True, show_provider_summary=False):
        return
    _ensure_service_browsers(service)
    if need_solver and not start_solver(thread_count=concurrency):
        print("无法启动 Solver，退出")
        return
    try:
        run_register_flow(count, 10, upload, concurrency, service)
    finally:
        if need_solver:
            stop_solver()


if __name__ == "__main__":
    main()
