import time

import requests


def check_url(
    url,
    expected_status=None,
    timeout=5,
    latency_warning_ms=1000,
):
    if expected_status is None:
        expected_status = [200]

    started = time.monotonic()

    try:
        response = requests.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={
                "User-Agent": "DSE-Sentinel/0.1",
            },
        )

        latency_ms = (
            time.monotonic() - started
        ) * 1000

        return {
            "available": True,
            "healthy": response.status_code in expected_status,
            "status_code": response.status_code,
            "latency_ms": round(latency_ms, 2),
            "latency_warning": (
                latency_ms > latency_warning_ms
            ),
            "final_url": response.url,
            "error": None,
        }

    except requests.exceptions.Timeout:
        return {
            "available": False,
            "healthy": False,
            "status_code": None,
            "latency_ms": round(
                (time.monotonic() - started) * 1000,
                2,
            ),
            "latency_warning": False,
            "final_url": None,
            "error": "timeout",
        }

    except requests.exceptions.ConnectionError as exc:
        return {
            "available": False,
            "healthy": False,
            "status_code": None,
            "latency_ms": round(
                (time.monotonic() - started) * 1000,
                2,
            ),
            "latency_warning": False,
            "final_url": None,
            "error": "connection_error",
            "error_detail": str(exc),
        }

    except requests.exceptions.RequestException as exc:
        return {
            "available": False,
            "healthy": False,
            "status_code": None,
            "latency_ms": round(
                (time.monotonic() - started) * 1000,
                2,
            ),
            "latency_warning": False,
            "final_url": None,
            "error": "request_error",
            "error_detail": str(exc),
        }
