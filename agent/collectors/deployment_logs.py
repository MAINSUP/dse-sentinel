import os
import re
from datetime import datetime, timezone


DEPLOYMENT_LOGS = [
    {
        "name": "MIA Mobile",
        "webhook_id": "mia-mobile-update",
        "log": "/home/mainsup/projects/MIA/webhook.log",
    },
    {
        "name": "SeaVie Mobile",
        "webhook_id": "seavie-mobile-update",
        "log": "/home/mainsup/projects/SEAVIE/webhook.log",
    },
]


ERROR_PATTERNS = [
    r"fatal:",
    r"error:",
    r"failed",
    r"failure",
    r"couldn't",
    r"cannot",
    r"permission denied",
    r"conflict",
    r"rejected",
]


def read_recent_lines(path, max_lines=100):
    try:
        with open(
            path,
            "r",
            encoding="utf-8",
            errors="replace",
        ) as file:
            return file.readlines()[-max_lines:]

    except OSError:
        return []


def classify_line(line):
    lower = line.lower()

    for pattern in ERROR_PATTERNS:
        if re.search(pattern, lower):
            return "error"

    if "webhook started" in lower:
        return "started"

    if "webhook finished" in lower:
        return "finished"

    if "already up to date" in lower:
        return "success"

    if "fast-forward" in lower:
        return "success"

    if "pulling" in lower:
        return "activity"

    return "info"


def collect_deployment_logs():
    results = []

    for deployment in DEPLOYMENT_LOGS:
        path = deployment["log"]

        exists = os.path.isfile(path)

        lines = read_recent_lines(path)

        entries = []

        for raw_line in lines:
            line = raw_line.rstrip()

            if not line:
                continue

            entries.append(
                {
                    "message": line,
                    "classification": classify_line(
                        line
                    ),
                }
            )

        errors = [
            entry
            for entry in entries
            if entry["classification"] == "error"
        ]

        results.append(
            {
                "name": deployment["name"],
                "webhook_id": deployment[
                    "webhook_id"
                ],
                "log": path,
                "exists": exists,
                "entries": entries,
                "error_count": len(errors),
                "errors": errors,
            }
        )

    return {
        "available": True,
        "deployments": results,
    }
