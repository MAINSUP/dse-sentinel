import re
from pathlib import Path
from datetime import datetime, timezone, timedelta


APPLICATION_LOGS = [
    {
        "name": "MIA Web",
        "type": "nextjs",
        "logs": [
            "/home/mainsup/projects/MIA/mia-web/webhook.log",
            "/home/mainsup/projects/MIA/mia-web/mia-web.log",
        ],
    },
    {
        "name": "MIA API",
        "type": "fastapi",
        "logs": [
            "/home/mainsup/projects/MIA/mia-api/api.log",
            "/home/mainsup/projects/MIA/mia-api/app.log",
        ],
    },
    {
        "name": "GitHub Webhook",
        "type": "webhook",
        "logs": [
            "/home/mainsup/projects/MIA/webhook.log",
            "/home/mainsup/projects/SEAVIE/webhook.log",
        ],
    },
]


ERROR_PATTERNS = [
    (re.compile(r"\b500\b"), "http_500"),
    (re.compile(r"\b502\b"), "http_502"),
    (re.compile(r"\b503\b"), "http_503"),
    (re.compile(r"\b504\b"), "http_504"),
    (re.compile(r"\bERROR\b", re.I), "error"),
    (re.compile(r"\bEXCEPTION\b", re.I), "exception"),
    (re.compile(r"\bTRACEBACK\b", re.I), "traceback"),
    (re.compile(r"\bFATAL\b", re.I), "fatal"),
    (re.compile(r"\bCRITICAL\b", re.I), "critical"),
    (re.compile(r"Unhandled", re.I), "unhandled_exception"),
    (re.compile(r"uncaught", re.I), "uncaught_exception"),
    (re.compile(r"ECONNREFUSED", re.I), "connection_refused"),
    (re.compile(r"ECONNRESET", re.I), "connection_reset"),
    (re.compile(r"ETIMEDOUT", re.I), "timeout"),
    (re.compile(r"database.*error", re.I), "database_error"),
    (re.compile(r"connection.*database", re.I), "database_connection"),
]


def _classify(message):
    for pattern, classification in ERROR_PATTERNS:
        if pattern.search(message):
            return classification

    return None


def _severity(classification):
    if classification in {
        "http_500",
        "http_502",
        "http_503",
        "http_504",
        "fatal",
        "critical",
        "unhandled_exception",
        "uncaught_exception",
        "database_connection",
    }:
        return "critical"

    if classification in {
        "exception",
        "traceback",
        "connection_refused",
        "database_error",
        "timeout",
    }:
        return "high"

    return "medium"


def _read_recent_lines(path, hours=24):
    file_path = Path(path)

    if not file_path.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    try:
        lines = file_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except Exception:
        return []

    results = []

    for line in lines[-5000:]:
        classification = _classify(line)

        if not classification:
            continue

        results.append({
            "message": line[:2000],
            "classification": classification,
            "severity": _severity(classification),
        })

    return results


def collect_application_errors(hours=24):
    applications = []
    incidents = []

    for app in APPLICATION_LOGS:
        app_errors = []

        for log_path in app["logs"]:
            entries = _read_recent_lines(log_path, hours)

            for entry in entries:
                entry["log"] = log_path
                app_errors.append(entry)

        # Deduplicate identical messages from different collectors/logs.
        unique = []
        seen = set()

        for entry in app_errors:
            key = (
                entry["classification"],
                entry["message"],
            )

            if key in seen:
                continue

            seen.add(key)
            unique.append(entry)

        applications.append({
            "name": app["name"],
            "type": app["type"],
            "error_count": len(unique),
            "errors": unique[-100:],
        })

        critical_count = sum(
            1 for e in unique
            if e["severity"] == "critical"
        )

        high_count = sum(
            1 for e in unique
            if e["severity"] == "high"
        )

        # Avoid creating incidents for one harmless error.
        if critical_count >= 3:
            incidents.append({
                "id": f"application:{app['type']}:critical-errors",
                "severity": "critical",
                "type": "application_errors",
                "title": f"{app['name']} has repeated critical errors",
                "description": (
                    f"{app['name']} produced {critical_count} "
                    f"critical application errors in the last {hours} hours."
                ),
                "metadata": {
                    "application": app["name"],
                    "type": app["type"],
                    "critical_count": critical_count,
                    "high_count": high_count,
                },
            })

        elif high_count >= 3:
            incidents.append({
                "id": f"application:{app['type']}:high-errors",
                "severity": "high",
                "type": "application_errors",
                "title": f"{app['name']} has repeated errors",
                "description": (
                    f"{app['name']} produced {high_count} "
                    f"high-severity errors in the last {hours} hours."
                ),
                "metadata": {
                    "application": app["name"],
                    "type": app["type"],
                    "critical_count": critical_count,
                    "high_count": high_count,
                },
            })

    return {
        "available": True,
        "window_hours": hours,
        "applications": applications,
        "incidents": incidents,
    }


if __name__ == "__main__":
    import json

    print(
        json.dumps(
            collect_application_errors(),
            indent=2,
        )
    )
