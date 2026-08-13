def detect_deployment_log_errors(data):
    incidents = []

    for deployment in data.get(
        "deployments",
        [],
    ):

        if deployment["error_count"] == 0:
            continue

        name = deployment["name"]

        for error in deployment["errors"]:

            incidents.append(
                {
                    "id": (
                        f"deployment:"
                        f"{deployment['webhook_id']}:"
                        f"log-error"
                    ),
                    "severity": "high",
                    "type": "deployment_failure",
                    "title": (
                        f"{name} deployment error"
                    ),
                    "description": (
                        f"Deployment log contains "
                        f"an error: "
                        f"{error['message']}"
                    ),
                    "metadata": {
                        "application": name,
                        "webhook_id": deployment[
                            "webhook_id"
                        ],
                        "log": deployment["log"],
                        "error": error[
                            "message"
                        ],
                    },
                }
            )

    return incidents
