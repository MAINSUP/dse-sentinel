def detect_deployment_problems(data):
    incidents = []

    deployments = data.get(
        "deployments",
        {},
    )

    for deployment in deployments.get(
        "deployments",
        [],
    ):

        name = deployment["name"]

        if not deployment["script_exists"]:
            incidents.append(
                {
                    "id": (
                        f"deployment:"
                        f"{deployment['webhook_id']}:"
                        f"script-missing"
                    ),
                    "severity": "critical",
                    "type": "deployment_script_missing",
                    "title": (
                        f"{name} deployment script missing"
                    ),
                    "description": (
                        f"Deployment script does not "
                        f"exist: "
                        f"{deployment['script']}"
                    ),
                    "metadata": deployment,
                }
            )

        elif not deployment["script_executable"]:
            incidents.append(
                {
                    "id": (
                        f"deployment:"
                        f"{deployment['webhook_id']}:"
                        f"script-not-executable"
                    ),
                    "severity": "high",
                    "type": "deployment_script_not_executable",
                    "title": (
                        f"{name} deployment script "
                        f"is not executable"
                    ),
                    "description": (
                        f"Deployment script exists but "
                        f"is not executable: "
                        f"{deployment['script']}"
                    ),
                    "metadata": deployment,
                }
            )

    return incidents
