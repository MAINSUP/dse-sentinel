def detect_application_failures(data):
    incidents = []

    for app in data.get(
        "applications",
        [],
    ):

        name = app["name"]
        app_type = app["type"]
        url = app["url"]

        # Application unreachable
        if not app["available"]:
            incidents.append(
                {
                    "id": (
                        f"application:"
                        f"{name}:unavailable"
                    ),
                    "severity": "critical",
                    "type": "application_unavailable",
                    "title": (
                        f"{name} unavailable"
                    ),
                    "description": (
                        f"{name} cannot be reached."
                    ),
                    "metadata": {
                        "application": name,
                        "type": app_type,
                        "url": url,
                        "error": app.get(
                            "error"
                        ),
                        "error_detail": app.get(
                            "error_detail"
                        ),
                    },
                }
            )

            continue

        status = app.get(
            "status_code"
        )

        # Server error
        if status is not None and status >= 500:
            incidents.append(
                {
                    "id": (
                        f"application:"
                        f"{name}:http-5xx"
                    ),
                    "severity": "critical",
                    "type": "http_5xx",
                    "title": (
                        f"{name} HTTP {status}"
                    ),
                    "description": (
                        f"{name} returned "
                        f"HTTP {status}."
                    ),
                    "metadata": {
                        "application": name,
                        "type": app_type,
                        "url": url,
                        "status_code": status,
                        "latency_ms": app.get(
                            "latency_ms"
                        ),
                    },
                }
            )

            continue

        # Client error
        if status is not None and 400 <= status < 500:
            incidents.append(
                {
                    "id": (
                        f"application:"
                        f"{name}:http-4xx"
                    ),
                    "severity": "medium",
                    "type": "http_4xx",
                    "title": (
                        f"{name} HTTP {status}"
                    ),
                    "description": (
                        f"{name} returned "
                        f"HTTP {status}."
                    ),
                    "metadata": {
                        "application": name,
                        "type": app_type,
                        "url": url,
                        "status_code": status,
                    },
                }
            )

        # Slow response
        if app.get("latency_warning"):
            incidents.append(
                {
                    "id": (
                        f"application:"
                        f"{name}:slow"
                    ),
                    "severity": "medium",
                    "type": "application_slow",
                    "title": (
                        f"{name} is slow"
                    ),
                    "description": (
                        f"{name} responded in "
                        f"{app['latency_ms']} ms."
                    ),
                    "metadata": {
                        "application": name,
                        "type": app_type,
                        "url": url,
                        "latency_ms": app[
                            "latency_ms"
                        ],
                    },
                }
            )

    return incidents