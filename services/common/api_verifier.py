import time
import logging
import requests as std_requests

logger = logging.getLogger(__name__)


def verify_api_key(api_key, endpoint, headers_builder, expected_status=200, timeout=30, json_body=None):
    if not api_key:
        logger.warning("verify_api_key: empty api_key, skipping")
        return None
    
    key_hint = f"{api_key[:16]}..." if len(api_key) > 16 else api_key
    transient_errors = (
        std_requests.exceptions.SSLError,
        std_requests.exceptions.ConnectionError,
        std_requests.exceptions.Timeout,
    )
    last_error = None

    for attempt in range(1, 4):
        try:
            response = std_requests.post(
                endpoint,
                headers=headers_builder(api_key),
                json=json_body,
                timeout=timeout,
            )
            break
        except transient_errors as exc:
            last_error = exc
            if attempt < 3:
                print(f"Warning: API key test [{key_hint}] encountered network/TLS error, retrying ({attempt}/3): {exc}")
                time.sleep(attempt)
                continue
            print(f"Warning: API key test [{key_hint}] failed after retries, cannot confirm key validity: {exc}")
            print("   This is typically caused by local proxy/TUN/DNS hijacking, not necessarily an invalid key.")
            return None
        except Exception as exc:
            print(f"Error: API key test failed: {exc}")
            return False
    else:
        print(f"Warning: API key test did not get a valid response: {last_error}")
        return None

    if response.status_code == expected_status:
        print(f"API key test passed [{key_hint}]")
        return True

    preview = response.text.strip().replace("\n", " ")[:160]
    print(f"Error: API key test [{key_hint}] failed: HTTP {response.status_code}")
    if preview:
        print(f"   Response: {preview}")
    return False
