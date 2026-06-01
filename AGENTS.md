# AGENTS.md

## 项目简介

自动化注册多个 API 服务（Firecrawl、Exa、Valyu、You、Serper）以获取 API Key，对 Key 做真实调用验证，并可选上传到 key-pool 服务器。包含一个 FastAPI Web 管理后台（`web/`）。

---

## 初始化

```bash
cp .env.example .env          # 填写 WEB_ADMIN_PASSWORD、WEB_SECRET_KEY、SERVER_URL
pip install -r requirements.txt
python -m patchright install --with-deps chromium   # Linux；macOS/Windows 去掉 --with-deps
```

无 `pyproject.toml`，无 `setup.cfg`，只用 `requirements.txt` + `venv`。

---

## 启动入口

| 命令 | 说明 |
|---|---|
| `python run.py` | 交互式 CLI 注册工具（自动引导 venv + 依赖） |
| `python web_start.py` | FastAPI Web 后台，端口 `WEB_PORT`（默认 8086） |
| `python api_solver.py` | 独立 Turnstile CAPTCHA Solver（端口 5073） |
| `docker compose up --build` | 启动 `app`（Web 后台）+ `solver` 容器 |

`run.py` 在模块顶层调用 `os.execv()` 以切换到 venv 重启自身。**在测试中 import `run.py` 前必须 patch `os.execv`** — 参见 `tests/test_run_bootstrap.py`。

---

## 测试

```bash
python -m pytest tests/                                              # 全量
python -m pytest tests/test_proxy_manager.py                        # 单文件
python -m pytest tests/test_proxy_manager.py::TestClass::test_name  # 单个用例
python -m unittest tests.test_config_placeholders                   # unittest 风格文件
```

无 `pytest.ini` / `pyproject.toml`，pytest 使用默认发现规则。

`tests/test_services/conftest.py` mock 了 `patchright.sync_api`，服务测试无需浏览器。**不要删除这个 stub。**

无 linter、formatter、typecheck、pre-commit 配置，无 CI 流水线。

---

## 架构关键点

### 邮件服务商配置在数据库，不在 `.env`

邮件服务商的 API Key / 域名存储在 `mail_providers` 表，通过 Web 后台（`/mail`）管理。`.env` 里的邮件变量（`EMAIL_PROVIDER`、`CLOUDFLARE_*`、`DUCKMAIL_*`、`ONLINEMAIL_*`）是遗留字段，只被 `cli/prompts.py` 的旧验证路径读取。

### HTTP 主路径 + 浏览器降级

`ExaService` 和 `ValyuService` 优先走 HTTP 注册，失败后降级到 patchright Chromium 浏览器。`FirecrawlService` 纯浏览器。基类见 `services/base.py`。

### Solver 只用于 Tavily

Turnstile Solver 子进程只在注册 Tavily 时启动（Tavily 当前上游已关闭注册入口）。以 Quart HTTP 服务运行在端口 5073。

### 账号输出文件是只追加的纯文本

`BaseService._save_result()` 将 `email,password,api_key` 追加到各服务独立的 `.txt` 文件（如 `exa_accounts.txt`），**同时**写入数据库。这些文件已 gitignore。

### 启动时自动执行迁移

`web_start.py` 启动时，`web/migration.py` 会将已有的 `.txt` 账号文件导入数据库。因有 `UNIQUE (service, api_key)` 约束，操作幂等。

### 浏览器缓存路径在模块加载时设定

`services/base.py` 在模块顶层调用 `os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '~/.cache/ms-playwright')`。如果 Chromium 二进制在其他位置，需覆盖此环境变量。

### APScheduler cron 使用 UTC

`web/scheduler.py` 中 `schedules` 表里的 cron 表达式均按 UTC 解析。

### 根目录的 `test_firecrawl.py` 已废弃

该文件引用了不再存在的模块（`mail_provider`、`firecrawl_core`）。除非明确要求，不要尝试运行或修复它。

### 无 JS 构建步骤

`web/static/` 存放已构建好的 HTML/JS/CSS，无 `npm`/`yarn`/`bun` 构建流程。

---

## 重要环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `WEB_ADMIN_PASSWORD` | `changeme` | 部署前务必修改 |
| `WEB_SECRET_KEY` | `change-this-...` | JWT 签名密钥 |
| `WEB_PORT` | `8086` | FastAPI 监听端口 |
| `DB_TYPE` | `sqlite` | `sqlite` 或 `postgresql` |
| `DB_PATH` | `web/data.db` | SQLite 文件路径 |
| `DB_URL` | `""` | PostgreSQL 连接 URL：`postgresql+asyncpg://...` |
| `SERVER_URL` | `""` | MySearch-Proxy 上传目标 |
| `PROXY_ENABLED` | `false` | 为 `true` 时 `PROXY_LIST` 必须非空，否则启动报 `ValueError` |
| `REGISTER_HEADLESS` | `true` | 设为 `false` 可在调试时看到浏览器窗口 |
| `SOLVER_PORT` | `5073` | Turnstile Solver 端口 |

完整列表含注释见 `.env.example`。

---

## Docker 持久化说明

默认 `docker-compose.yml` 未为 `web/data.db` 声明 volume。如需跨容器重启保留数据库，请将 volume 挂载到 `/app/web/`。

---

## Development environment (Windows + WSL)

`./venv` 由 WSL 创建，是 Linux venv，结构为：

```
./venv/bin/python        ← WSL / Docker 可用
./venv/Scripts/python.exe  ← Windows 侧不可用（无 pyvenv.cfg，缺少 Lib/site-packages）
```

**不要在 PowerShell 里重建 `./venv`**。在 Windows 侧 `py -m venv venv` 会覆盖掉 `bin/` 目录，WSL 和 Docker 均无法再使用。

从 PowerShell 执行项目代码，须通过 `wsl.exe` 转发：

```powershell
wsl.exe -e bash -c "cd /mnt/d/workspace/tavily-key-generator && ./venv/bin/python -c 'import requests; print(requests.__version__)'"
```

需要重建 venv 时，在 WSL 终端里操作：

```bash
# Ubuntu 没有安装 python3.x-venv 包时，用 --without-pip 绕过 ensurepip
python3 -m venv --without-pip venv
# 然后用系统 pip 或手动 bootstrap 安装依赖
pip3 install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

Windows 侧没有带项目依赖的系统级 Python（`py -0` 列出的 uv 管理环境均未安装 `requests` 等依赖），所有依赖只在 WSL venv 里。
