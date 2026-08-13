import os
import subprocess
import time


DEPLOYMENTS = [
    {
        "name": "MIA Mobile",
        "webhook_id": "mia-mobile-update",
        "script": "/home/mainsup/projects/MIA/update-mobile.sh",
        "working_directory": "/home/mainsup/projects/MIA",
    },
    {
        "name": "SeaVie Mobile",
        "webhook_id": "seavie-mobile-update",
        "script": "/home/mainsup/projects/SEAVIE/update-seavie-mobile.sh",
        "working_directory": "/home/mainsup/projects/SEAVIE",
    },
]


def collect_deployments():
    results = []

    for deployment in DEPLOYMENTS:
        script = deployment["script"]

        exists = os.path.isfile(script)
        executable = os.access(script, os.X_OK)

        results.append(
            {
                "name": deployment["name"],
                "webhook_id": deployment["webhook_id"],
                "script": script,
                "working_directory": deployment[
                    "working_directory"
                ],
                "script_exists": exists,
                "script_executable": executable,
            }
        )

    return {
        "available": True,
        "deployments": results,
    }
