import re


HIGH_PATTERNS = [
    r"segmentation fault",
    r"out of memory",
    r"oom-killer",
    r"kernel panic",
    r"failed to start",
    r"fatal",
    r"critical",
]


MEDIUM_PATTERNS = [
    r"connection refused",
    r"connection reset",
    r"timeout",
    r"failed",
    r"error",
    r"cannot",
    r"unable",
]


SECURITY_PATTERNS = [
    r"authentication failure",
    r"failed password",
    r"invalid user",
    r"break-in attempt",
    r"permission denied",
]


def _matches(message, patterns):
    if not message:
        return False

    text = message.lower()

    return any(
        re.search(pattern, text)
        for pattern in patterns
    )


def check_journal_errors(journal):
    incidents = []

    if not journal.get("available"):
        return incidents

    for entry in journal.get("entries", []):

        message = entry.get("message") or ""

        systemd_unit = (
            entry.get("systemd_unit")
            or "unknown"
        )

        timestamp = entry.get("timestamp")

        # ---------------------------------------------
        # Security
        # ---------------------------------------------

        if _matches(message, SECURITY_PATTERNS):

            incidents.append(
                {
                    "id": (
                        "journal:security:"
                        f"{systemd_unit}:"
                        f"{message[:80]}"
                    ),
                    "severity": "high",
                    "type": "security_log_event",
                    "title": "Security-related journal event",
                    "description": message,
                    "metadata": {
                        "unit": systemd_unit,
                        "timestamp": timestamp,
                        "pid": entry.get("pid"),
                        "source": "systemd-journal",
                    },
                }
            )

            continue

        # ---------------------------------------------
        # Critical
        # ---------------------------------------------

        if _matches(message, HIGH_PATTERNS):

            incidents.append(
                {
                    "id": (
                        "journal:critical:"
                        f"{systemd_unit}:"
                        f"{message[:80]}"
                    ),
                    "severity": "critical",
                    "type": "journal_critical",
                    "title": "Critical system log event",
                    "description": message,
                    "metadata": {
                        "unit": systemd_unit,
                        "timestamp": timestamp,
                        "pid": entry.get("pid"),
                        "source": "systemd-journal",
                    },
                }
            )

            continue

        # ---------------------------------------------
        # Medium
        # ---------------------------------------------

        if _matches(message, MEDIUM_PATTERNS):

            incidents.append(
                {
                    "id": (
                        "journal:error:"
                        f"{systemd_unit}:"
                        f"{message[:80]}"
                    ),
                    "severity": "medium",
                    "type": "journal_error",
                    "title": "Service error detected",
                    "description": message,
                    "metadata": {
                        "unit": systemd_unit,
                        "timestamp": timestamp,
                        "pid": entry.get("pid"),
                        "source": "systemd-journal",
                    },
                }
            )

    return incidents
