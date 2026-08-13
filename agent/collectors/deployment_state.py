import os
import re
import json
from datetime import datetime, timezone


STATE_FILE = "/home/mainsup/projects/dse-sentinel/agent/deployment_state.json"

INCOMPLETE_DEPLOYMENT_TIMEOUT_SECONDS = 15 * 60

DEPLOYMENTS = [
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
    r"\bfatal:",
    r"\berror:",
    r"\bfailed\b",
    r"\bfailure\b",
    r"permission denied",
    r"\bconflict\b",
    r"\brejected\b",
    r"\bcouldn't\b",
    r"\bcannot\b",
]


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return {}


def save_state(state):
    directory = os.path.dirname(STATE_FILE)

    os.makedirs(
        directory,
        exist_ok=True,
    )

    temp_file = STATE_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            state,
            f,
            indent=2,
        )

    os.replace(
        temp_file,
        STATE_FILE,
    )


def is_error(line):
    lower = line.lower()

    return any(
        re.search(
            pattern,
            lower,
        )
        for pattern in ERROR_PATTERNS
    )


def parse_timestamp(line):
    match = re.search(
        r"([A-Z][a-z]{2}\s+"
        r"[A-Z][a-z]{2}\s+"
        r"\d{1,2}\s+"
        r"\d{2}:\d{2}:\d{2}\s+"
        r"UTC\s+"
        r"\d{4})",
        line,
    )

    if not match:
        return None

    try:
        dt = datetime.strptime(
            re.sub(
                r"\s+",
                " ",
                match.group(1),
            ),
            "%a %b %d %H:%M:%S UTC %Y",
        )

        return dt.replace(
            tzinfo=timezone.utc
        ).isoformat()

    except ValueError:
        return None


def timestamp_age_seconds(timestamp):
    if not timestamp:
        return None

    try:
        dt = datetime.fromisoformat(
            timestamp
        )

        return (
            datetime.now(timezone.utc) - dt
        ).total_seconds()

    except ValueError:
        return None


def read_log(path):
    try:
        with open(
            path,
            "r",
            encoding="utf-8",
            errors="replace",
        ) as f:
            return f.readlines()

    except OSError:
        return []


def parse_runs(lines):
    runs = []

    current = None

    for raw_line in lines:
        line = raw_line.rstrip()

        if not line:
            continue

        timestamp = parse_timestamp(
            line
        )

        lower = line.lower()

        if "webhook started" in lower:

            current = {
                "started_at": timestamp,
                "finished_at": None,
                "lines": [],
                "errors": [],
                "success": False,
                "finished": False,
            }

            runs.append(current)

            continue

        if current is None:
            continue

        current["lines"].append(line)

        if is_error(line):
            current["errors"].append(line)

        if "webhook finished" in lower:

            current["finished"] = True
            current["finished_at"] = timestamp

    for run in runs:

        if run["errors"]:
            run["success"] = False

        elif not run["finished"]:
            run["success"] = False

        else:

            success_markers = [
                "already up to date",
                "fast-forward",
            ]

            run["success"] = any(
                marker in line.lower()
                for line in run["lines"]
                for marker in success_markers
            )

    return runs


def summarize_latest_run(
    deployment,
    runs,
):
    if not runs:

        return {
            "name": deployment["name"],
            "webhook_id": deployment[
                "webhook_id"
            ],
            "status": "no_runs",
            "latest_run": None,
        }

    latest = runs[-1]

    if latest["errors"]:

        status = "failed"

    elif not latest["finished"]:

        age = timestamp_age_seconds(
            latest["started_at"]
        )

        if (
            age is not None
            and age > INCOMPLETE_DEPLOYMENT_TIMEOUT_SECONDS
        ):
            status = "stale_incomplete"

        else:
            status = "incomplete"

    elif latest["success"]:

        status = "success"

    else:

        status = "unknown"

    return {
        "name": deployment["name"],
        "webhook_id": deployment[
            "webhook_id"
        ],
        "status": status,
        "latest_run": latest,
    }


def collect_deployment_state():

    state = load_state()

    deployments = []
    incidents = []

    for deployment in DEPLOYMENTS:

        lines = read_log(
            deployment["log"]
        )

        runs = parse_runs(lines)

        summary = summarize_latest_run(
            deployment,
            runs,
        )

        deployments.append(summary)

        webhook_id = deployment[
            "webhook_id"
        ]

        latest = summary["latest_run"]

        if summary["status"] == "failed":

            incidents.append(
                {
                    "id": (
                        f"deployment:"
                        f"{webhook_id}:failure"
                    ),
                    "severity": "high",
                    "type": "deployment_failure",
                    "title": (
                        f"{deployment['name']} "
                        f"deployment failed"
                    ),
                    "description": (
                        latest["errors"][0]
                    ),
                    "metadata": {
                        "application": deployment[
                            "name"
                        ],
                        "webhook_id": webhook_id,
                        "started_at": latest[
                            "started_at"
                        ],
                        "finished_at": latest[
                            "finished_at"
                        ],
                        "errors": latest[
                            "errors"
                        ],
                    },
                }
            )

        elif summary["status"] == "incomplete":

            incidents.append(
                {
                    "id": (
                        f"deployment:"
                        f"{webhook_id}:incomplete"
                    ),
                    "severity": "high",
                    "type": "deployment_incomplete",
                    "title": (
                        f"{deployment['name']} "
                        f"deployment still running"
                    ),
                    "description": (
                        "Webhook started but "
                        "has not finished within "
                        "the expected time."
                    ),
                    "metadata": {
                        "application": deployment[
                            "name"
                        ],
                        "webhook_id": webhook_id,
                        "started_at": latest[
                            "started_at"
                        ],
                    },
                }
            )

        elif summary["status"] == "stale_incomplete":

            # Historical incomplete webhook.
            # Do not create an active incident.
            pass

    result = {
        "available": True,
        "deployments": deployments,
        "incidents": incidents,
    }

    state["last_collection"] = result

    save_state(state)

    return result


if __name__ == "__main__":

    print(
        json.dumps(
            collect_deployment_state(),
            indent=2,
        )
    )