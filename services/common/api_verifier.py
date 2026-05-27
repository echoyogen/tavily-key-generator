import time
import requests as std_requests


def verify_api_key(api_key, endpoint, headers_builder, expected_status=200, timeout=30):
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
                timeout=timeout,
            )
            break
        except transient_errors as exc:
            last_error = exc
            if attempt < 3:
                print(f"Warning: API key test encountered network/TLS error, retrying ({attempt}/3): {exc}")
                time.sleep(attempt)
                continue
            print(f"Warning: API key test failed after retries, cannot confirm key validity: {exc}")
            print("   This is typically caused by local proxy/TUN/DNS hijacking, not necessarily an invalid key.")
            return None
        except Exception as exc:
            print(f"Error: API key test failed: {exc}")
            return False
    else:
        print(f"Warning: API key test did not get a valid response: {last_error}")
        return None

    if response.status_code == expected_status:
        print("API key test passed")
        return True

    preview = response.text.strip().replace("\n", " ")[:160]
    print(f"Error: API key test failed: HTTP {response.status_code}")
    if preview:
        print(f"   Response: {preview}")
    return False
