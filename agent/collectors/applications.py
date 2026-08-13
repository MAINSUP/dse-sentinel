from application_config import APPLICATIONS
from collectors.http import check_url


def collect_applications():
    results = []

    for application in APPLICATIONS:
        result = check_url(
            url=application["health_url"],
            expected_status=application.get(
                "expected_status",
                [200],
            ),
            timeout=application.get(
                "timeout",
                5,
            ),
            latency_warning_ms=application.get(
                "latency_warning_ms",
                1000,
            ),
        )

        result.update(
            {
                "name": application["name"],
                "type": application["type"],
                "url": application["health_url"],
            }
        )

        if "public_url" in application:
            result["public_url"] = application[
                "public_url"
            ]

        results.append(result)

    return {
        "available": True,
        "applications": results,
    }