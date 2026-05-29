# Learnings

## 2026-05-29 Session ses_18da4286bffeE2iF2yT8xz44Ig

### Codebase Patterns
- YouService (`services/you/service.py`) is the authoritative pattern: fully overrides `register()`, bypasses BaseService browser flow, uses requests.Session() with warm-up
- BaseService abstract methods must all be overridden but stubs just `raise NotImplementedError`
- YouService abstract stubs at lines 316-332 show the exact format
- `_save_result` in YouService overrides default with custom format; for Valyu keep default `email,password,api_key\n`
- `_open_browser` is also overridden with `raise NotImplementedError` in YouService (line 316-317)

### Valyu Technical Details
- Supabase URL: `https://auth.valyu.ai`, Anon Key: `sb_publishable_8AbrTfadTWE6iBwyjzK2TA_mJJbL0G6`
- Platform URL: `https://platform.valyu.ai`
- Onboarding: POST `platform.valyu.ai/onboarding?email=...&provider=email`
  - Content-Type: `text/plain;charset=UTF-8`
  - next-action header required (dynamic, fallback: `4049b0f006c0cc849cd70fb479842ca0d4c4bbade9`)
  - Body: JSON array with single dict, captchaToken="$undefined"
- Password login: POST `auth.valyu.ai/auth/v1/token?grant_type=password`
- API key page: `platform.valyu.ai/user/account/apikeys`
- Verification email: Supabase magic link format `auth.valyu.ai/auth/v1/verify?token=...`

### Current valyu/service.py
- Has `_VALYU_KEY_RE = re.compile(r'val[a-z_]*[A-Za-z0-9_-]{20,}')` at line 8 - must preserve
- Has `_detect_signup_result`, `_wait_for_signup_result` free functions - can discard (replaced by HTTP approach)
- Browser-based implementation: `_navigate_to_signup`, `_fill_form`, `_submit_form`, `_verify_email`, `_extract_api_key`
- Has `_do_post_verify` but uses `verify_api_key` from api_verifier.py (must change per plan)

### Key Constraints
- MUST NOT modify: `services/base.py`, `mail/base.py`, `services/common/api_verifier.py`
- MUST NOT call `super().register()` 
- `_do_post_verify` must NOT use `verify_api_key` function (needs body param, that function doesn't support it)
- `get_verification_link` does NOT accept skip_ids parameter
- existing_ids snapshot IS done in register() before calling onboarding, but NOT passed to get_verification_link

### Import patterns
- Only standard libs + requests + config + services.base in main service
- `from mail.factory import get_provider` imported inside methods (not at top level)
- `import config` used directly for `config.EMAIL_CODE_TIMEOUT`
