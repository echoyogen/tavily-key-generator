# Valyu 注册重写：HTTP API 主路径 + 浏览器 Fallback

## TL;DR

> **Quick Summary**: 完整重写 `services/valyu/service.py`，将当前已损坏的浏览器流替换为 HTTP-only 主路径（参照 YouService 模式），并实现完整的 11 步浏览器 onboarding 作为 fallback。
>
> **Deliverables**:
> - `services/valyu/service.py`：完整重写（~420 行）
> - `tests/test_services/test_valyu_service.py`：新增（替换已废弃的 wait strategy 测试）
> - `tests/test_services/test_valyu_wait_strategy.py`：删除
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Task 1 → Tasks 2/3/4/5 → Task 6 → Task 7/8

---

## Context

### Original Request
重写 ValyuService，优先 API 方案，浏览器方案作为 fallback，反爬参考 YouService。

### Research Findings
- **Valyu 技术栈**：Next.js (Vercel) + Supabase Auth (`auth.valyu.ai`)，Turnstile 被 CSP 阻止（`captchaToken="$undefined"` 可通过）
- **注册 API 端点**：`POST platform.valyu.ai/onboarding?email=...&provider=email`，需 `next-action` header + `text/plain;charset=UTF-8` Content-Type，body 为 JSON array
- **`next-action` hash 动态性**：每次 Vercel 重部署都会变更，必须动态提取；参考脚本硬编码 `4049b0f006c0cc849cd70fb479842ca0d4c4bbade9` 作为 fallback
- **验证 email**：Supabase magic link，格式 `auth.valyu.ai/auth/v1/verify?token=...`，`primary_host_hints` 中已有 "auth"，`mail/base.py` 无需改动
- **登录**：`POST auth.valyu.ai/auth/v1/token?grant_type=password`，返回 `access_token`
- **API key 页面**：`platform.valyu.ai/user/account/apikeys`，需要 Supabase session cookies

### YouService Anti-Bot Patterns (参照实现)
- `requests.Session()` 全程 cookie 持久化
- Warm-up GET 让 Cloudflare 建立 `uuid_guest` cookie
- 分离 `_NAV_HEADERS`（页面导航）和 `_CORS_HEADERS`（API 调用），`sec-fetch-site` 值不同
- 动态提取 `next-action` hash + hardcoded fallback
- 调用 `provider.get_existing_message_ids(email)` 在发邮件前快照，避免复用旧消息

### Metis 审查识别到的已解决问题
- **架构冲突**：选定方案 A——`register()` 全部内联，abstract methods 全部 stub `raise NotImplementedError`
- **测试文件**：`test_valyu_wait_strategy.py` 测试已废弃的浏览器行为，明确删除并重写
- **`mail/base.py`**：无需改动，"auth" 已在 `primary_host_hints`，`auth.valyu.ai` 自动匹配
- **`api_verifier.py`**：无需改动，`_do_post_verify()` 内联 `requests.post()` 附带请求体
- **`get_verification_link` skip_ids**：新注册账号不存在旧验证链接，无需 skip_ids，`mail/base.py` 不变
- **`_save_result()` 格式**：Valyu 是密码注册，保持默认 `email,password,api_key\n`

---

## Work Objectives

### Core Objective
将 ValyuService 从一个无法运行的浏览器实现，重写为以 HTTP API 为主、Camoufox 浏览器为 fallback 的注册流程，并恢复测试覆盖。

### Concrete Deliverables
- `services/valyu/service.py`：完整重写，HTTP 主路径 + 浏览器 fallback
- `tests/test_services/test_valyu_service.py`：新建，覆盖 HTTP 成功路径 + fallback 触发 + next-action 提取降级
- `tests/test_services/test_valyu_wait_strategy.py`：删除

### Definition of Done
- [ ] `python -c "from services.valyu.service import ValyuService; print('import ok')"` 无错误
- [ ] `pytest tests/test_services/test_valyu_service.py -v` 全部通过（0 failures）
- [ ] `pytest tests/ -v --ignore=tests/test_services/test_valyu_service.py` 不出现新的失败

### Must Have
- HTTP 主路径：warm-up → onboarding POST（动态 next-action）→ 等验证邮件 → verify link → 密码登录 → 提取 API key
- Supabase 直连降级：onboarding POST 失败时自动切换到 `POST /auth/v1/signup`
- 浏览器 fallback：HTTP 全链路失败时，使用 Camoufox 完成完整 11 步 onboarding
- Anti-bot：warm-up GET + Session cookie 持久 + 分离 nav/cors headers + next-action 动态提取
- 测试：HTTP 成功路径 mock 测试 + fallback 触发测试 + next-action 降级测试

### Must NOT Have (Guardrails)
- 不修改 `services/base.py`、`mail/base.py`、`services/common/api_verifier.py`
- 不使用 `super().register()` 调用 BaseService 的浏览器流程（直接调 `_browser_fallback`）
- 不留任何 "optional" 功能描述，每个功能明确在 scope 内
- 不硬编码 `next-action` 为唯一方案，必须先动态提取，失败才 fallback 到硬编码常量
- 不在 abstract method stubs 外实现任何浏览器逻辑（浏览器代码全在 `_browser_fallback()`）
- `_do_post_verify` 不依赖 `api_verifier.py` 的 `verify_api_key()`（需要 body，而该函数无 body 参数）

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES（pytest，在 `tests/` 目录）
- **Automated tests**: Tests-after（先实现，最后 Task 7 补测试）
- **Framework**: pytest + unittest.mock

### QA Policy
每个任务的 QA 使用 Bash (`python -c`) 做 import 和单元级 smoke test。
复杂集成路径通过 Task 7 的 Mock 测试覆盖。

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (立即开始 - scaffold):
└── Task 1: service.py 完整骨架（所有常量 + 方法 stub）[quick]

Wave 2 (Wave 1 完成后 - 4 并行，各自实现不同方法组):
├── Task 2: HTTP 初始化模块（warm_up + get_onboarding_page + submit_onboarding + supabase_fallback）[unspecified-high]
├── Task 3: 验证模块（wait_and_verify + verify_via_link + password_login）[unspecified-high]
├── Task 4: Key 获取 + 后处理（fetch_api_key_http + extract_key + _do_post_verify + _save_result）[unspecified-high]
└── Task 5: 浏览器 fallback（_browser_fallback 11 步 + abstract method stubs）[unspecified-high]

Wave 3 (Wave 2 完成后 - 2 并行):
├── Task 6: 串联 register() + 异常处理 + fallback 触发逻辑（depends: 2,3,4,5）[deep]
└── Task 7: 删除旧测试 + 新建 test_valyu_service.py（独立文件，并行安全）[unspecified-high]

Wave FINAL (全部完成后 - 4 并行审查):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real QA execution (unspecified-high)
└── F4: Scope fidelity check (deep)
→ Present results → Get explicit user okay
```

### Dependency Matrix
- **1**: none → 2, 3, 4, 5
- **2**: 1 → 6
- **3**: 1 → 6
- **4**: 1 → 6
- **5**: 1 → 6
- **6**: 2, 3, 4, 5 → F1-F4
- **7**: 1 → F1-F4 (独立，与 Task 6 并行)

### Agent Dispatch Summary
- Wave 1: 1 × `quick`
- Wave 2: 4 × `unspecified-high`（各自独立，使用 Edit 填充骨架 stub，不使用 Write 覆盖整个文件）
- Wave 3: 1 × `deep` + 1 × `unspecified-high`
- Wave FINAL: `oracle` + `unspecified-high` + `unspecified-high` + `deep`

---

## TODOs

- [x] 1. service.py 完整骨架：常量 + 所有方法 stub

  **What to do**:
  - 完整重写 `services/valyu/service.py`，建立后续任务可以 Edit 填充的骨架结构
  - 顶部模块文档注释说明 HTTP 认证链路（与 YouService 格式一致）
  - 定义所有模块级常量（每个都在单独一行，便于后续 Edit 精确定位）：
    - `SUPABASE_URL = "https://auth.valyu.ai"`
    - `SUPABASE_ANON_KEY = "sb_publishable_8AbrTfadTWE6iBwyjzK2TA_mJJbL0G6"`
    - `PLATFORM_URL = "https://platform.valyu.ai"`
    - `_FALLBACK_ACTION_ID = "4049b0f006c0cc849cd70fb479842ca0d4c4bbade9"`
    - `_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"` （与 YouService 版本号一致）
    - `_VALYU_KEY_RE = re.compile(r'val[a-z_]*[A-Za-z0-9_-]{20,}')`
  - 定义名字池和 onboarding 选项池（原样从参考脚本提取，作为模块级 tuple，不使用 list）：
    - `_FIRST_NAMES`：使用参考脚本 `valyu_auto_register.py` 中的完整列表
    - `_LAST_NAMES`：同上
    - `_HEARD_FROM`：`("linkedin","twitter","reddit","search","github","friend","other")` 等合法枚举值
    - `_ROLES`：`("ai_developer","non_ai_developer","founder_cto","vibe_coder","researcher","other")`
    - `_INDUSTRIES`：`("technology","finance","healthcare","education","research","media_entertainment","other")`
    - `_TECHNOLOGIES`：`("ai_sdk","openai_sdk","langchain","mcp","n8n","non_technical")`
  - 定义 Header 字典（3 个）：
    - `_NAV_HEADERS`：页面导航用，`sec-fetch-dest=document, sec-fetch-mode=navigate`，不含 origin
    - `_SUPABASE_HEADERS`：Supabase API 调用用，含 `apikey: SUPABASE_ANON_KEY, Content-Type: application/json`
    - `_PLATFORM_CORS_HEADERS`：platform.valyu.ai CORS 请求用，含 `origin, sec-fetch-mode=cors, sec-fetch-site=same-origin`
  - 定义 `ValyuService` 类（class body 全部为 stub），方法定义顺序：
    1. 类属性：`name, signup_url, api_key_prefix, output_file, headless_config_key`（`signup_url = "https://platform.valyu.ai/auth"`）
    2. `register(self, email, password): pass  # Task 6`（一行注释标注哪个 Task 实现）
    3. HTTP 初始化组（Task 2）：`_warm_up, _get_onboarding_page_html, _submit_onboarding, _supabase_signup_fallback`
    4. 验证组（Task 3）：`_wait_and_verify_email, _verify_via_link, _password_login`
    5. Key 获取组（Task 4）：`_fetch_api_key_http, _extract_valyu_key, _do_post_verify, _save_result`
    6. 浏览器 fallback（Task 5）：`_browser_fallback`
    7. Abstract method stubs（Task 5）：`_open_browser, _navigate_to_signup, _fill_form, _submit_form, _verify_email, _extract_api_key` — 全部 `raise NotImplementedError(...)`

  **Must NOT do**:
  - 不在 stub 方法体内写任何实现逻辑（全部 `pass` 或 `raise NotImplementedError`）
  - 不删除或修改 `_VALYU_KEY_RE`（保留现有 regex，Task 4 会使用）
  - 不使用 list 定义选项池（用 tuple，避免可变全局状态）
  - 不使用任何非标库 import（只 import re, time, random, string, requests, config, services.base）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 纯 scaffold 编写，逻辑简单，主要是正确组织代码结构
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1（单独）
  - **Blocks**: Tasks 2, 3, 4, 5
  - **Blocked By**: None（可立即开始）

  **References**:
  - `services/you/service.py:24-63` — 模块文档注释格式、常量定义方式、header 字典结构
  - `services/you/service.py:66-101` — 类属性定义顺序、register() override 骨架
  - `services/you/service.py:314-332` — Abstract method stubs 格式（`raise NotImplementedError`）
  - `/mnt/c/Users/lanxb/Downloads/valyu_auto_register.py:38-75` — 名字池和选项池原始数据
  - `services/valyu/service.py:8` — 现有 `_VALYU_KEY_RE` 定义（原样保留）

  **Acceptance Criteria**:
  - [ ] `python -c "from services.valyu.service import ValyuService; s = ValyuService(); print(s.name)"` 输出 `valyu`
  - [ ] `python -c "from services.valyu.service import SUPABASE_URL, SUPABASE_ANON_KEY, PLATFORM_URL, _FALLBACK_ACTION_ID; print('ok')"` 无错误
  - [ ] `python -c "from services.valyu.service import _VALYU_KEY_RE; print(_VALYU_KEY_RE.pattern)"` 输出 `val[a-z_]*[A-Za-z0-9_-]{20,}`

  **QA Scenarios**:
  ```
  Scenario: 类属性验证
    Tool: Bash (python -c)
    Steps:
      1. python -c "from services.valyu.service import ValyuService; s = ValyuService(); assert s.name == 'valyu'; assert s.signup_url == 'https://platform.valyu.ai/auth'; assert s.output_file == 'valyu_accounts.txt'"
    Expected Result: 无异常输出
    Evidence: .sisyphus/evidence/task-1-class-attrs.txt

  Scenario: Abstract stubs 触发 NotImplementedError
    Tool: Bash (python -c)
    Steps:
      1. python -c "
  from unittest.mock import MagicMock
  from services.valyu.service import ValyuService
  s = ValyuService()
  try:
      s._navigate_to_signup(MagicMock())
      assert False, 'should raise'
  except NotImplementedError:
      print('ok')
  "
    Expected Result: ok
    Evidence: .sisyphus/evidence/task-1-stubs.txt
  ```

  **Commit**: YES（独立 commit，后续 Tasks 用 --amend 或 fixup）
  - Message: `refactor(valyu): rewrite service scaffold with HTTP-primary layout`

- [x] 2. HTTP 初始化模块：warm_up + onboarding 提交 + Supabase fallback

  **What to do**:
  - 使用 Edit 工具（不用 Write）在 Task 1 生成的 stub 中替换以下方法的实现：
  - `_warm_up(self, sess: requests.Session) -> None`：
    - GET `platform.valyu.ai/auth` 带 `_NAV_HEADERS`，timeout=15
    - 目的：让 Cloudflare 设置访客 cookie，不处理响应
    - 异常只打印 warning，不 raise
  - `_get_onboarding_page_html(self, sess, email) -> tuple[str, str]`：
    - GET `{PLATFORM_URL}/onboarding?email={email}&provider=email` 带 `_NAV_HEADERS + sec-fetch-site=same-origin + referer={PLATFORM_URL}/auth`
    - 从 HTML 动态提取 next-action hash：
      - 正则搜索 `$ACTION_1:0` form field，与 YouService `_extract_action_params` 一致：
        `re.search(r'name="\$ACTION_1:0" value="([^"]+)"', html)`
      - 从 `$ACTION_1:0` value 中提取 id：`re.search(r'"id"\s*:\s*"([0-9a-f]{40,})"', unescape(m.group(1)))`
      - 失败时使用 `_FALLBACK_ACTION_ID` 并打印 `[valyu] WARNING: using fallback next-action ID`
    - 返回 `(html, action_id)`
  - `_submit_onboarding(self, sess, email, password) -> bool`：
    - 调用 `_get_onboarding_page_html()` 获取 action_id
    - 随机选取 firstName/lastName/username（email 前缀 strip 特殊字符）
    - 随机选取 heardFrom/role/industry/tech 各取一个合法值
    - 构建 payload（JSON array，单个 dict，参照参考脚本的完整字段集合，captchaToken="$undefined"）
    - POST `{PLATFORM_URL}/onboarding?email={email}&provider=email`，Headers：
      - `Content-Type: text/plain;charset=UTF-8`
      - `Accept: text/x-component`
      - `next-action: {action_id}`
      - `Referer: {PLATFORM_URL}/onboarding?email={email}&provider=email`
      - `Origin: {PLATFORM_URL}`
      - `sec-fetch-site: same-origin`
      - `sec-fetch-mode: cors`
      - `User-Agent: _UA`
    - 判断成功：status in (200, 302, 303) 且 response 不含 `"error"` 关键字
    - 返回 bool；失败时打印响应前 300 字符
  - `_supabase_signup_fallback(self, sess, email, password) -> bool`：
    - POST `{SUPABASE_URL}/auth/v1/signup` 带 `_SUPABASE_HEADERS`
    - body: `{"email": email, "password": password}`
    - 成功条件：status == 200 且响应 JSON 含 "id" 字段
    - 已注册（422 含 "User already registered"）→ 打印 warning，返回 True（已有账号，继续等验证邮件）
    - 其他失败 → 打印错误内容，返回 False

  **Must NOT do**:
  - 不使用 Write 工具覆盖整个文件（只用 Edit 精确替换方法 stub）
  - 不在 `_submit_onboarding` 中调用任何邮件 provider（邮件等待是 Task 3 的责任）
  - onboarding payload 的枚举值必须来自骨架中定义的常量池，不能用魔术字符串
  - 不忽略 `_get_onboarding_page_html` 失败——即使 GET 失败也要 fallback 到 `_FALLBACK_ACTION_ID` 继续尝试

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: HTTP 逆向实现，需要准确处理 Next.js Server Action 协议和 Supabase Auth API
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2（与 Tasks 3, 4, 5 并行）
  - **Blocks**: Task 6
  - **Blocked By**: Task 1

  **References**:
  - `services/you/service.py:106-111` — `_warm_up` 实现模板
  - `services/you/service.py:265-278` — 动态 next-action 提取（`_extract_action_params`），直接移植此模式
  - `/mnt/c/Users/lanxb/Downloads/valyu_auto_register.py:259-318` — `submit_onboarding` 完整 payload 字段（含所有 `$undefined` 字段）
  - `/mnt/c/Users/lanxb/Downloads/valyu_auto_register.py:195-229` — `ValyuAuthClient.signup` Supabase fallback 实现
  - `services/you/service.py:125-166` — signup/signin fallback 切换模式（Valyu 用于 Supabase 422 处理）

  **Acceptance Criteria**:
  - [ ] `python -c "from services.valyu.service import ValyuService; import inspect; src = inspect.getsource(ValyuService._warm_up); assert 'platform.valyu.ai' in src; print('warm_up ok')"` 通过
  - [ ] `python -c "from services.valyu.service import ValyuService; import inspect; src = inspect.getsource(ValyuService._submit_onboarding); assert 'text/plain;charset=UTF-8' in src; assert 'next-action' in src; print('onboarding ok')"` 通过
  - [ ] `python -c "from services.valyu.service import ValyuService; import inspect; src = inspect.getsource(ValyuService._supabase_signup_fallback); assert '/auth/v1/signup' in src; print('supabase fallback ok')"` 通过

  **QA Scenarios**:
  ```
  Scenario: next-action 动态提取成功
    Tool: Bash (python -c)
    Steps:
      1. python -c "
  import html as _h, re
  from services.valyu.service import _FALLBACK_ACTION_ID
  # 模拟包含 action ID 的 HTML
  html_with_action = 'name=\"\$ACTION_1:0\" value=\"{&quot;id&quot;:&quot;abcdef1234567890abcdef1234567890abcdef1234&quot;,&quot;bound&quot;:&quot;\$@1&quot;}\"'
  m0 = re.search(r'name=\"\\\$ACTION_1:0\" value=\"([^\"]+)\"', html_with_action)
  mid = re.search(r'\"id\"\s*:\s*\"([0-9a-f]{40,})\"', _h.unescape(m0.group(1)) if m0 else '')
  action_id = mid.group(1) if mid else _FALLBACK_ACTION_ID
  assert action_id == 'abcdef1234567890abcdef1234567890abcdef1234', f'got {action_id}'
  print('dynamic extraction ok')
  "
    Expected Result: dynamic extraction ok
    Evidence: .sisyphus/evidence/task-2-next-action.txt

  Scenario: next-action 提取失败时使用 fallback
    Tool: Bash (python -c)
    Steps:
      1. python -c "
  from services.valyu.service import _FALLBACK_ACTION_ID
  import re, html as _h
  html_no_action = '<html><body>no action here</body></html>'
  m0 = re.search(r'name=\"\\\$ACTION_1:0\" value=\"([^\"]+)\"', html_no_action)
  mid = re.search(r'\"id\"\s*:\s*\"([0-9a-f]{40,})\"', _h.unescape(m0.group(1)) if m0 else '')
  action_id = mid.group(1) if mid else _FALLBACK_ACTION_ID
  assert action_id == _FALLBACK_ACTION_ID, f'fallback not used: {action_id}'
  print('fallback ok')
  "
    Expected Result: fallback ok
    Evidence: .sisyphus/evidence/task-2-next-action-fallback.txt
  ```

  **Commit**: NO（与其他 Wave 2 任务合并到 Task 6 commit）

- [x] 3. 验证模块：等待验证邮件 + 访问 verify link + 密码登录

  **What to do**:
  - 使用 Edit 工具替换以下 stub 实现：
  - `_wait_and_verify_email(self, email) -> str | None`：
    - 注意：此方法在发邮件 *之后* 被调用，返回验证链接 URL
    - 调用 `from mail.factory import get_provider; provider = get_provider()`
    - 调用 `provider.get_verification_link(email, timeout=config.EMAIL_CODE_TIMEOUT)` 等待验证链接
    - 返回 link string，失败返回 None 并打印 error
    - 不要在此方法内 snapshot existing IDs（snapshot 在 register() 发邮件前做）
  - `_verify_via_link(self, sess, link) -> bool`：
    - `sess.get(link, headers=_NAV_HEADERS, allow_redirects=True, timeout=60)`
    - 成功条件：最终 URL 包含 `platform.valyu.ai`
    - 失败（非 2xx 或 URL 仍在 auth.valyu.ai）→ 打印 warning，返回 False
    - 等待 Supabase redirect 链跳转完成后 `time.sleep(2)`
  - `_password_login(self, sess, email, password) -> str | None`：
    - POST `{SUPABASE_URL}/auth/v1/token?grant_type=password` 带 `_SUPABASE_HEADERS`
    - body: `{"email": email, "password": password}`
    - 成功：返回 `data["access_token"]`
    - 失败：打印错误，返回 None

  **Must NOT do**:
  - `_wait_and_verify_email` 不调用 `get_existing_message_ids`（这由 `register()` 在调用前负责）
  - `_verify_via_link` 不处理 JavaScript 重定向（requests 只跟 HTTP 3xx，JS redirect 不跟进）
  - 不在 `_password_login` 中存储 token 到实例变量（由 `register()` 接收返回值管理）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Supabase Auth API 调用 + 邮件 provider 集成
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2（与 Tasks 2, 4, 5 并行）
  - **Blocks**: Task 6
  - **Blocked By**: Task 1

  **References**:
  - `services/you/service.py:168-199` — `_verify_otp`：cookie 验证后的 session 确认模式
  - `/mnt/c/Users/lanxb/Downloads/valyu_auto_register.py:204-211` — `ValyuAuthClient.login` Supabase token 调用
  - `/mnt/c/Users/lanxb/Downloads/valyu_auto_register.py:231-234` — `verify_via_link` 实现
  - `mail/base.py:28-38` — `get_verification_link` 签名和参数（timeout, 无 skip_ids）
  - `config.py:120` — `EMAIL_CODE_TIMEOUT` 配置项

  **Acceptance Criteria**:
  - [ ] `python -c "from services.valyu.service import ValyuService; import inspect; src = inspect.getsource(ValyuService._password_login); assert 'grant_type=password' in src; print('login ok')"` 通过
  - [ ] `python -c "from services.valyu.service import ValyuService; import inspect; src = inspect.getsource(ValyuService._verify_via_link); assert 'allow_redirects=True' in src; print('verify ok')"` 通过

  **QA Scenarios**:
  ```
  Scenario: 验证 link 跟随重定向到 platform 视为成功
    Tool: Bash (python -c)
    Steps:
      1. python -c "
  from unittest.mock import MagicMock, patch
  from services.valyu.service import ValyuService
  import requests
  s = ValyuService()
  mock_resp = MagicMock()
  mock_resp.status_code = 200
  mock_resp.url = 'https://platform.valyu.ai/dashboard'
  sess = MagicMock()
  sess.get.return_value = mock_resp
  with patch('time.sleep'):
      result = s._verify_via_link(sess, 'https://auth.valyu.ai/auth/v1/verify?token=abc')
  assert result == True, f'expected True, got {result}'
  print('verify link success ok')
  "
    Expected Result: verify link success ok
    Evidence: .sisyphus/evidence/task-3-verify-link.txt

  Scenario: 登录失败返回 None
    Tool: Bash (python -c)
    Steps:
      1. python -c "
  from unittest.mock import MagicMock
  from services.valyu.service import ValyuService
  s = ValyuService()
  mock_resp = MagicMock()
  mock_resp.status_code = 400
  mock_resp.json.return_value = {'error': 'invalid_grant'}
  mock_resp.text = 'invalid_grant'
  sess = MagicMock()
  sess.post.return_value = mock_resp
  result = s._password_login(sess, 'test@example.com', 'wrongpass')
  assert result is None, f'expected None, got {result}'
  print('login failure ok')
  "
    Expected Result: login failure ok
    Evidence: .sisyphus/evidence/task-3-login-fail.txt
  ```

  **Commit**: NO（合并到 Task 6）

- [x] 4. Key 获取 + 后处理：fetch_api_key_http + _do_post_verify + _save_result

  **What to do**:
  - 使用 Edit 工具替换以下 stub 实现：
  - `_extract_valyu_key(self, text) -> str | None`：
    - 用 `_VALYU_KEY_RE.findall(text)` 提取，返回第一个匹配或 None
  - `_fetch_api_key_http(self, sess, access_token) -> str | None`：
    - GET `{PLATFORM_URL}/user/account/apikeys`，Headers 附加：
      - `Authorization: Bearer {access_token}`
      - `_NAV_HEADERS` + `sec-fetch-site: same-origin`
    - 先尝试从响应文本提取 key：`self._extract_valyu_key(resp.text)`
    - 若无 key，尝试 Server Action 创建：
      - 从页面 HTML 动态提取 action 参数（同 Task 2 的 `_extract_action_params` 模式）
      - POST 同 URL 以 `multipart/form-data`，Headers 含 `next-action`、`accept: text/x-component`
      - 从 RSC 响应中提取 key：`self._extract_valyu_key(create_resp.text)`
    - 仍无 key 则返回 None，打印 "[valyu] Could not extract API key from HTTP response"
  - `_do_post_verify(self, api_key) -> None`：
    - 若 api_key 为 None/空，直接返回
    - 直接用 `import requests as std_requests`：
      ```python
      r = std_requests.post(
          "https://api.valyu.ai/v1/search",
          json={"query": "test", "max_num_results": 1},
          headers={"x-api-key": api_key, "Content-Type": "application/json"},
          timeout=getattr(config, "API_KEY_TIMEOUT", 30),
      )
      ```
    - 200 → 打印 "[valyu] API key verification passed"
    - 非 200 → 打印 warning，不 raise（saving anyway 语义）
    - 网络异常 → 打印 warning，不 raise
  - `_save_result(self, email, password, api_key) -> None`：
    - 使用 `BaseService._SAVE_LOCK`
    - 格式：`f"{email},{password},{api_key}\n"`（默认 BaseService 格式，不 override 也可以，但显式写出便于文档化）

  **Must NOT do**:
  - `_do_post_verify` 不调用 `from services.common.api_verifier import verify_api_key`（需要 body 而 verify_api_key 不支持）
  - `_fetch_api_key_http` 中如果 Server Action 创建返回非 200，打印 warning 后返回 None，不 raise

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: YouService 的 Server Action 创建模式移植 + API key 提取
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2（与 Tasks 2, 3, 5 并行）
  - **Blocks**: Task 6
  - **Blocked By**: Task 1

  **References**:
  - `services/you/service.py:201-263` — `_create_api_key` 完整实现（Server Action 模式直接移植）
  - `services/you/service.py:281-284` — `_extract_key_from_rsc` 模式（改用 `_VALYU_KEY_RE`）
  - `services/valyu/service.py:8` — 现有 `_VALYU_KEY_RE` 定义
  - `services/you/service.py:290-305` — `_do_post_verify` 内联 requests.get 模式（Valyu 改为 post）
  - `services/base.py:86-89` — `_save_result` BaseService 默认实现（若直接 override 则格式一致）

  **Acceptance Criteria**:
  - [ ] `python -c "from services.valyu.service import ValyuService, _VALYU_KEY_RE; s=ValyuService(); k=s._extract_valyu_key('..valyu_abc123XYZ789DEF456GHI..'); assert k is not None; print('key extract ok')"` 通过
  - [ ] `python -c "from services.valyu.service import ValyuService; import inspect; src=inspect.getsource(ValyuService._do_post_verify); assert 'api.valyu.ai/v1/search' in src; assert 'verify_api_key' not in src; print('post verify ok')"` 通过

  **QA Scenarios**:
  ```
  Scenario: key 提取成功
    Tool: Bash (python -c)
    Steps:
      1. python -c "
  from services.valyu.service import ValyuService
  s = ValyuService()
  fake_html = 'some content valyu_k8mNpQrStUvWxYz1234567890 more content'
  key = s._extract_valyu_key(fake_html)
  assert key is not None and key.startswith('valyu_'), f'got {key}'
  print('extract ok:', key)
  "
    Expected Result: extract ok: valyu_k8mNpQrStUvWxYz1234567890
    Evidence: .sisyphus/evidence/task-4-key-extract.txt

  Scenario: _do_post_verify 不依赖 api_verifier
    Tool: Bash (python -c)
    Steps:
      1. python -c "
  import inspect
  from services.valyu.service import ValyuService
  src = inspect.getsource(ValyuService._do_post_verify)
  assert 'verify_api_key' not in src, '_do_post_verify must not use verify_api_key'
  assert 'api.valyu.ai/v1/search' in src
  assert 'application/json' in src
  print('post verify independence ok')
  "
    Expected Result: post verify independence ok
    Evidence: .sisyphus/evidence/task-4-post-verify.txt
  ```

  **Commit**: NO（合并到 Task 6）

- [x] 5. 浏览器 fallback：_browser_fallback 11 步 + abstract method stubs

  **What to do**:
  - 使用 Edit 工具替换 `_browser_fallback` stub 和所有 abstract method stubs
  - `_browser_fallback(self, email, password) -> str | None`：
    - 调用 `browser_cm = BaseService._open_browser(self)` 获取 Camoufox 实例
    - 注意：`_open_browser` 返回 context manager，需要 `__enter__` / `__exit__`（参照 `base.py:38-55`）
    - 实现完整 11 步 onboarding，全部使用 Camoufox 同步 API（`page.goto`, `page.fill`, `page.click`, `page.wait_for_url`, `page.wait_for_selector` 等）：
      1. `page.goto(f"{PLATFORM_URL}/auth", wait_until="domcontentloaded", timeout=30000)` + `time.sleep(2)`
      2. 等待并 fill `input[placeholder="name@example.com"]` + click `button:has-text("Continue with Email")` + `page.wait_for_url("**/onboarding**", timeout=15000)`
      3. fill `input[name="firstName"]` 或 `input:below(:text("First name"))` with `random.choice(_FIRST_NAMES)`；fill lastName 同理
      4. click password toggle：`page.locator('button[role="switch"]:near(:text("Use password"))').click()`；`page.wait_for_selector('input[type="password"]', timeout=5000)`
      5. fill password + confirm password（`page.locator('input[type="password"]').nth(0)/.nth(1)`）
      6. click `button:has-text("Continue"):not([disabled])` + `time.sleep(1)`
      7. click `button:has-text("Developer")` + click Continue
      8. click source button（随机从 `["LinkedIn","Twitter/X","Reddit","Search Engine","GitHub"]`）+ click Continue
      9. click role button（随机从 `["AI Developer","Founder/CTO","Vibe Coder","Researcher"]`）+ click Continue
      10. click `button:has-text("Technology")` + click Continue
      11. click tech button（随机从 `["MCP","OpenAI SDK","LangChain","AI SDK"]`）+ click Continue → scroll-to-bottom if visible → checkbox → `button:has-text("Finish setup")`
    - 调用 `_wait_and_verify_email(email)` 等待 verify link
    - 如有 link 则 `page.goto(link, wait_until="domcontentloaded", timeout=60000)` + `time.sleep(5)`
    - Navigate 到 `/user/account/apikeys`，尝试 `_extract_api_key(page)`（使用现有浏览器提取逻辑）
    - 调用 `_do_post_verify(api_key)` + `_save_result(email, password, api_key)` + return api_key
    - 任何 Exception：打印 `[valyu] Browser fallback failed: {e}`，return None
  - Abstract method stubs（6 个）全部用 `raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")` 替换：
    - `_open_browser(self)` — 也 raise（fallback 直接调 `BaseService._open_browser(self)`，不走 abstract 路径）
    - `_navigate_to_signup(self, page)`, `_fill_form(self, page, email, password)`, `_submit_form(self, page)`, `_verify_email(self, page, email)`, `_extract_api_key(self, page)` — 全部 raise

  **Must NOT do**:
  - 不调用 `super().register()`（会触发 `_open_browser` 的 `raise NotImplementedError`）
  - 不在 abstract stubs 外实现任何浏览器逻辑（所有浏览器代码只在 `_browser_fallback`）
  - `_browser_fallback` 中不 raise 异常（catch all 后 return None）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 复杂多步浏览器操作，需要准确处理 Camoufox/Playwright 同步 API 和 selector
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2（与 Tasks 2, 3, 4 并行）
  - **Blocks**: Task 6
  - **Blocked By**: Task 1

  **References**:
  - `/mnt/c/Users/lanxb/Downloads/valyu_auto_register.py:328-424` — `register_via_browser` 完整 11 步（Async Playwright，转换为 Camoufox 同步 API）
  - `services/base.py:37-55` — `register()` 中 `browser_cm.__enter__()`/`__exit__()` 用法（直接移植 try/finally 模式）
  - `services/valyu/service.py:215-248` — 现有 `_extract_api_key` 实现（在 `_browser_fallback` 末尾复用）
  - `services/you/service.py:314-332` — abstract stub `raise NotImplementedError` 格式参照

  **Acceptance Criteria**:
  - [ ] `python -c "from services.valyu.service import ValyuService; import inspect; src=inspect.getsource(ValyuService._browser_fallback); assert 'Continue with Email' in src; assert '_extract_api_key' in src; print('browser fallback ok')"` 通过
  - [ ] `python -c "from unittest.mock import MagicMock; from services.valyu.service import ValyuService; s=ValyuService(); [getattr(s, m) for m in ['_navigate_to_signup','_fill_form','_submit_form']]; print('stubs exist ok')"` 通过（确认方法存在）

  **QA Scenarios**:
  ```
  Scenario: abstract stubs 全部触发 NotImplementedError
    Tool: Bash (python -c)
    Steps:
      1. python -c "
  from unittest.mock import MagicMock
  from services.valyu.service import ValyuService
  s = ValyuService()
  stubs = [
      lambda: s._navigate_to_signup(MagicMock()),
      lambda: s._fill_form(MagicMock(), 'e@t.com', 'pwd'),
      lambda: s._submit_form(MagicMock()),
      lambda: s._verify_email(MagicMock(), 'e@t.com'),
      lambda: s._extract_api_key(MagicMock()),
  ]
  for i, fn in enumerate(stubs):
      try:
          fn()
          assert False, f'stub {i} should raise NotImplementedError'
      except NotImplementedError:
          pass
  print('all stubs raise ok')
  "
    Expected Result: all stubs raise ok
    Evidence: .sisyphus/evidence/task-5-stubs.txt

  Scenario: _browser_fallback 包含完整 11 步关键字检查
    Tool: Bash (python -c)
    Steps:
      1. python -c "
  import inspect
  from services.valyu.service import ValyuService
  src = inspect.getsource(ValyuService._browser_fallback)
  required = ['Continue with Email', 'Developer', 'Finish setup', '_FIRST_NAMES', 'password']
  for kw in required:
      assert kw in src, f'missing: {kw}'
  print('browser fallback completeness ok')
  "
    Expected Result: browser fallback completeness ok
    Evidence: .sisyphus/evidence/task-5-browser-completeness.txt
  ```

  **Commit**: NO（合并到 Task 6）

- [x] 6. 串联 register()：完整流程 + 异常处理 + fallback 触发

  **What to do**:
  - 使用 Edit 工具替换 `register(self, email, password)` 的 `pass` stub
  - 最终 `register()` 实现，串联 Tasks 2/3/4/5 各方法，完整逻辑：
    ```
    1. sess = requests.Session()
    2. _warm_up(sess)
    3. provider = get_provider()
    4. existing_ids = provider.get_existing_message_ids(email)  # 快照现有消息
    5. ok = _submit_onboarding(sess, email, password)
       如失败: ok = _supabase_signup_fallback(sess, email, password)
       如仍失败: print warn, return _browser_fallback(email, password)
    6. verify_link = provider.get_verification_link(email, timeout=config.EMAIL_CODE_TIMEOUT)
       如 None: print err, return _browser_fallback(email, password)
    7. _verify_via_link(sess, verify_link)  (失败只 warn，继续，cookies 可能已设置)
    8. time.sleep(2)
    9. access_token = _password_login(sess, email, password)
       如 None: print warn, return _browser_fallback(email, password)
    10. api_key = _fetch_api_key_http(sess, access_token)
        如 None: print warn, return _browser_fallback(email, password)
    11. _do_post_verify(api_key)
    12. _save_result(email, password, api_key)
    13. return api_key
    ```
    全程 try/except Exception as e 包裹（步骤 2-13）：catch 时 `print(f"[valyu] HTTP flow error: {e}, falling back to browser")` 然后 `return self._browser_fallback(email, password)`
  - 注意：`existing_ids` 不传给 `get_verification_link()`（该方法不接受 skip_ids 参数）
  - 在触发 browser fallback 前打印具体失败步骤，格式 `[valyu] Step N failed: <reason>, falling back to browser`

  **Must NOT do**:
  - 不调用 `super().register()`
  - 不内联任何 HTTP 逻辑（全部委托给已实现的方法）
  - fallback 不能静默触发（必须有 print 输出指明原因）

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要精确理解 Tasks 2-5 所有方法的返回值契约，组合成正确的错误传播和 fallback 触发逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES（与 Task 7 并行）
  - **Parallel Group**: Wave 3
  - **Blocks**: F1-F4
  - **Blocked By**: Tasks 2, 3, 4, 5

  **References**:
  - `services/you/service.py:76-100` — YouService.register() 完整实现（整体模式：warm-up → auth → key create → verify → save）
  - `services/you/service.py:119-123` — `get_existing_message_ids` 调用时机（在触发 OTP 之前）
  - `services/base.py:37-55` — BaseService.register() 的 try/finally 模式（fallback 的 browser_cm 需要同样的 cleanup）

  **Acceptance Criteria**:
  - [ ] `python -c "from services.valyu.service import ValyuService; import inspect; src=inspect.getsource(ValyuService.register); assert 'get_existing_message_ids' in src; assert '_browser_fallback' in src; assert 'get_verification_link' in src; print('register wired ok')"` 通过

  **QA Scenarios**:
  ```
  Scenario: HTTP 成功路径全程 mock
    Tool: Bash (python -c)
    Steps:
      1. python -c "
  from unittest.mock import MagicMock, patch
  from services.valyu.service import ValyuService

  s = ValyuService()
  mock_provider = MagicMock()
  mock_provider.get_existing_message_ids.return_value = set()
  mock_provider.get_verification_link.return_value = 'https://auth.valyu.ai/auth/v1/verify?token=abc'

  with patch('mail.factory.get_provider', return_value=mock_provider), \
       patch.object(s, '_warm_up'), \
       patch.object(s, '_submit_onboarding', return_value=True), \
       patch.object(s, '_verify_via_link', return_value=True), \
       patch.object(s, '_password_login', return_value='tok_test123'), \
       patch.object(s, '_fetch_api_key_http', return_value='valyu_testkey12345678901234'), \
       patch.object(s, '_do_post_verify'), \
       patch.object(s, '_save_result'), \
       patch('time.sleep'):
      result = s.register('test@tmp.com', 'Pass123!')

  assert result == 'valyu_testkey12345678901234', f'got {result}'
  print('HTTP success path ok')
  "
    Expected Result: HTTP success path ok
    Evidence: .sisyphus/evidence/task-6-http-success.txt

  Scenario: onboarding + supabase 均失败时触发 browser fallback
    Tool: Bash (python -c)
    Steps:
      1. python -c "
  from unittest.mock import MagicMock, patch
  from services.valyu.service import ValyuService

  s = ValyuService()
  mock_provider = MagicMock()
  mock_provider.get_existing_message_ids.return_value = set()
  browser_called = []

  def fake_browser(email, password):
      browser_called.append(True)
      return 'valyu_browserfallbackkey123456'

  with patch('mail.factory.get_provider', return_value=mock_provider), \
       patch.object(s, '_warm_up'), \
       patch.object(s, '_submit_onboarding', return_value=False), \
       patch.object(s, '_supabase_signup_fallback', return_value=False), \
       patch.object(s, '_browser_fallback', side_effect=fake_browser):
      result = s.register('test@tmp.com', 'Pass123!')

  assert browser_called, 'browser fallback was not triggered'
  assert result == 'valyu_browserfallbackkey123456', f'got {result}'
  print('fallback trigger ok')
  "
    Expected Result: fallback trigger ok
    Evidence: .sisyphus/evidence/task-6-fallback-trigger.txt
  ```

  **Commit**: YES（Task 1-6 合并此处提交）
  - Message: `refactor(valyu): rewrite service to HTTP-only primary with browser fallback`
  - Files: `services/valyu/service.py`
  - Pre-commit: `python -c "from services.valyu.service import ValyuService; print('import ok')"`

- [x] 7. 删除旧测试 + 新建 test_valyu_service.py

  **What to do**:
  - 删除 `tests/test_services/test_valyu_wait_strategy.py`（`git rm` 或直接删除文件）
  - 新建 `tests/test_services/test_valyu_service.py`，覆盖以下测试类：
  - `TestValyuServiceHttpPrimary`（HTTP 主路径）：
    - `test_register_http_success`：mock 全链路，register() 返回正确 key，_browser_fallback 未被调用
    - `test_register_fallbacks_to_browser_when_onboarding_fails`：onboarding 和 supabase 均返回 False → _browser_fallback 被调用
    - `test_register_fallbacks_to_browser_when_token_is_none`：_password_login 返回 None → _browser_fallback 被调用
    - `test_register_fallbacks_to_browser_on_unexpected_exception`：_warm_up 抛出 Exception → _browser_fallback 被调用
  - `TestValyuServiceNextAction`（next-action 提取）：
    - `test_dynamic_next_action_extracted_from_html`：HTML 含有 `$ACTION_1:0` value → 返回正确 action_id（不使用 fallback）
    - `test_fallback_action_id_used_when_no_match`：HTML 无 action data → 返回 `_FALLBACK_ACTION_ID`
  - `TestValyuServiceExtractKey`（key 提取）：
    - `test_extract_valyu_key_found`：文本含 `valyu_xxx` 格式 → 返回匹配值
    - `test_extract_valyu_key_not_found`：文本不含 valyu key → 返回 None
  - `TestValyuServiceImports`（smoke test）：
    - `test_module_imports`：`from services.valyu.service import ValyuService, SUPABASE_URL, SUPABASE_ANON_KEY` 无异常
    - `test_class_attributes`：`name == "valyu"`, `signup_url == "https://platform.valyu.ai/auth"`, `output_file == "valyu_accounts.txt"`

  **Must NOT do**:
  - 不写任何需要真实网络连接的测试（全部 Mock）
  - 不测试 `_browser_fallback` 的内部浏览器操作（浏览器测试需要真实环境，不在此 scope）
  - 不为 `test_valyu_wait_strategy.py` 中的旧测试写等价版本（旧测试测的是已废弃行为）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要深理解新 service.py 的方法契约来写有效的 Mock 测试
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES（与 Task 6 并行，操作独立文件）
  - **Parallel Group**: Wave 3
  - **Blocks**: F1-F4
  - **Blocked By**: Task 1（需要 import service 以确认方法存在）

  **References**:
  - `tests/test_services/test_valyu_wait_strategy.py` — 待删除的文件（用 git rm 删除，不保留）
  - `services/you/service.py` — YouService Mock 测试写法参照（该项目对 YouService 无单元测试，参照项目其他测试文件风格）
  - `tests/test_config_placeholders.py` — 项目测试文件风格参照（unittest + 标准 import 结构）

  **Acceptance Criteria**:
  - [ ] `ls tests/test_services/test_valyu_wait_strategy.py` 输出 `No such file or directory`
  - [ ] `pytest tests/test_services/test_valyu_service.py -v` 全部通过（0 failures, 0 errors）
  - [ ] `pytest tests/ -v --ignore=tests/test_services/test_valyu_service.py` 通过，pass 数量与重写前持平

  **QA Scenarios**:
  ```
  Scenario: 新测试全部通过
    Tool: Bash
    Steps:
      1. pytest tests/test_services/test_valyu_service.py -v 2>&1 | tee .sisyphus/evidence/task-7-pytest.txt
      2. grep -E "passed|failed|error" .sisyphus/evidence/task-7-pytest.txt
    Expected Result: "X passed, 0 failed, 0 errors"（X >= 10）
    Evidence: .sisyphus/evidence/task-7-pytest.txt

  Scenario: 其他测试不受影响
    Tool: Bash
    Steps:
      1. pytest tests/ -v --ignore=tests/test_services/test_valyu_service.py 2>&1 | tail -5
    Expected Result: 与重写前相比，没有新增失败项
    Evidence: .sisyphus/evidence/task-7-other-tests.txt

  Scenario: 旧测试文件已删除
    Tool: Bash
    Steps:
      1. python -c "import os; assert not os.path.exists('tests/test_services/test_valyu_wait_strategy.py'), 'file still exists'; print('deleted ok')"
    Expected Result: deleted ok
    Evidence: .sisyphus/evidence/task-7-old-test-deleted.txt
  ```

  **Commit**: YES（独立 commit）
  - Message: `test(valyu): replace wait-strategy tests with HTTP flow coverage`
  - Files: `tests/test_services/test_valyu_service.py`（新增），`tests/test_services/test_valyu_wait_strategy.py`（删除）
  - Pre-commit: `pytest tests/test_services/test_valyu_service.py -v`

---

## Final Verification Wave

> 4 个 review agent 并行运行，全部通过后向用户展示结果，等待明确 "okay" 再结束。

- [x] F1. **Plan Compliance Audit** — `oracle`
  读取本计划 Must Have/Must NOT Have，逐条验证 `services/valyu/service.py`：HTTP 主路径完整（warm-up→onboarding→verify→login→apikey）、Supabase fallback 存在、浏览器 fallback 存在、abstract methods 全部 stub `raise NotImplementedError`、`api_verifier.py` 未修改、`mail/base.py` 未修改。
  Output: `Must Have [N/N] | Must NOT Have [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  运行 `python -c "from services.valyu.service import ValyuService"` 和 `pytest tests/ -v --tb=short`，检查：无 `as any`/空 except、无 console.log 残留、无 as any 滥用、无硬编码 token/key（SUPABASE_ANON_KEY 是公开 anon key，允许存在）、next-action fallback 有 WARNING 日志。
  Output: `Import [PASS/FAIL] | Tests [N pass/N fail] | Lint issues [N] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high`
  从干净状态执行所有 test_valyu_service.py 中的 Mock 测试场景，验证：HTTP 成功路径断言、fallback 触发断言、next-action 提取降级断言；用 `pytest tests/ -v --ignore=tests/test_services/test_valyu_service.py` 确认其他服务测试未受影响。
  Output: `Scenarios [N/N pass] | Other services [N/N green] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  对照 Must NOT 列表：确认 `services/base.py`、`mail/base.py`、`services/common/api_verifier.py` 未被修改（`git diff HEAD -- services/base.py mail/base.py services/common/api_verifier.py` 应为空）；确认 `test_valyu_wait_strategy.py` 已删除；确认其他 services 文件未被意外修改。
  Output: `Protected files [N/N unchanged] | Deleted files [CONFIRMED/MISSING] | Unaccounted changes [CLEAN/N] | VERDICT`

---

## Commit Strategy

- Task 1-6: `refactor(valyu): rewrite service to HTTP-only primary with browser fallback` — `services/valyu/service.py`
- Task 7: `test(valyu): replace wait-strategy tests with HTTP flow coverage` — `tests/test_services/test_valyu_service.py`，并含 `git rm tests/test_services/test_valyu_wait_strategy.py`

---

## Success Criteria

### Verification Commands
```bash
# Import OK
python -c "from services.valyu.service import ValyuService; print('ok')"
# Expected: ok

# New tests pass
pytest tests/test_services/test_valyu_service.py -v
# Expected: all PASSED, 0 failures

# Old tests gone
ls tests/test_services/test_valyu_wait_strategy.py
# Expected: No such file

# Other services unaffected
pytest tests/ -v --ignore=tests/test_services/test_valyu_service.py
# Expected: same pass count as before this work
```

### Final Checklist
- [ ] HTTP 主路径完整实现（6 步）
- [ ] Supabase 直连 fallback 完整
- [ ] 浏览器 fallback 完整（11 步 onboarding）
- [ ] `next-action` 动态提取 + hardcoded fallback 双保险
- [ ] `get_existing_message_ids` 快照在发邮件前调用
- [ ] `api_verifier.py`、`base.py`、`mail/base.py` 未被修改
- [ ] `test_valyu_wait_strategy.py` 已删除
- [ ] `test_valyu_service.py` 覆盖 3 个核心场景
