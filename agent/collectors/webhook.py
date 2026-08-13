import subprocess


def collect_webhook_service():
    try:
        result = subprocess.run(
            [
                "systemctl",
                "is-active",
                "webhook",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        active = result.stdout.strip() == "active"

        return {
            "available": True,
            "service": "webhook",
            "active": active,
            "status": result.stdout.strip(),
        }

    except Exception as exc:
        return {
            "available": False,
            "service": "webhook",
            "active": False,
            "status": "unknown",
            "error": str(exc),
        }
