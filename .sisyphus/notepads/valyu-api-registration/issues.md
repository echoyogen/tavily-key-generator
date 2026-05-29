# Issues / Gotchas

## 2026-05-29 Session ses_18da4286bffeE2iF2yT8xz44Ig

### Wave 2 Coordination
- Tasks 2, 3, 4, 5 all Edit the same file (services/valyu/service.py)
- Each task should only edit its own method group's stubs
- DO NOT use Write tool to overwrite - only Edit for precise stub replacement
- If two agents accidentally overwrite each other's work, need to merge manually

### Abstract Method Note
- `_open_browser` is NOT abstract in BaseService (it has a real implementation at line 91)
- But it must be overridden in ValyuService with `raise NotImplementedError` (like YouService line 316)
- This is to prevent accidental browser launches in HTTP flow

### `_save_result` Decision
- BaseService._save_result already writes `email,password,api_key\n` format
- Valyu uses password registration so this default is correct
- Can just NOT override `_save_result` OR explicitly override with same logic
- Plan says "explicitly write out for documentation"
- BUT YouService explicitly overrides with different format (OTP_ONLY)
- For Valyu: use BaseService._SAVE_LOCK pattern but write `email,password,api_key\n`

### `_wait_and_verify_email` vs direct `get_verification_link`
- Plan Task 3 says: implement `_wait_and_verify_email` that calls provider.get_verification_link
- Plan Task 6 says: register() calls `provider.get_verification_link` directly (NOT `_wait_and_verify_email`)
- Wait - re-reading Task 6: step 6 says `verify_link = provider.get_verification_link(...)` 
- BUT Task 5 says _browser_fallback calls `_wait_and_verify_email(email)`
- So `_wait_and_verify_email` is used ONLY in browser fallback, not in HTTP path
- HTTP path in register() calls provider directly

### `_extract_api_key` in browser fallback
- Task 5 says _browser_fallback should call `_extract_api_key(page)` at the end
- But _extract_api_key IS a stub that raises NotImplementedError
- Re-reading: "Navigate 到 /user/account/apikeys，尝试 _extract_api_key(page)（使用现有浏览器提取逻辑）"
- This is a contradiction - abstract stub raises NotImplementedError
- RESOLUTION: The _browser_fallback must include its OWN key extraction inline (using _VALYU_KEY_RE on page.content()), 
  OR it should keep _extract_api_key with actual implementation but the stub comment says raise NotImplementedError
- Looking at plan mustnot: "不在 abstract method stubs 外实现任何浏览器逻辑（浏览器代码全在 _browser_fallback()）"
- So _extract_api_key raises NotImplementedError, and _browser_fallback handles key extraction inline

### Verification flow note
- `_verify_via_link` return value: plan says "失败只 warn，继续" in Task 6 step 7
- So even if verify fails, we proceed (cookies may have been set)
