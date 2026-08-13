import json
import shutil
import subprocess

from config import WATCHED_SERVICES, WATCHED_PM2


def systemd_status(service):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True,
            text=True,
            timeout=5,
        )

        status = result.stdout.strip()

        return {
            "name": service,
            "status": status,
            "running": status == "active",
        }

    except Exception as exc:
        return {
            "name": service,
            "status": "error",
            "running": False,
            "error": str(exc),
        }


def get_systemd_services():
    return [
        systemd_status(service)
        for service in WATCHED_SERVICES
    ]


def get_pm2_processes():
    pm2_path = shutil.which("pm2")

    if not pm2_path:
        return {
            "available": False,
            "error": "PM2 executable not found",
        }

    try:
        result = subprocess.run(
            [pm2_path, "jlist"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return {
                "available": False,
                "error": result.stderr.strip(),
            }

        if not result.stdout.strip():
            return {
                "available": True,
                "processes": [],
            }

        processes = json.loads(result.stdout)

        output = []

        for process in processes:
            name = process.get("name")
            env = process.get("pm2_env", {})
            monit = process.get("monit", {})

            # If WATCHED_PM2 is empty, monitor all PM2 processes.
            if WATCHED_PM2 and name not in WATCHED_PM2:
                continue

            output.append(
                {
                    "id": process.get("pm_id"),
                    "name": name,
                    "pid": process.get("pid"),
                    "status": env.get("status"),
                    "mode": env.get("exec_mode"),
                    "version": env.get("node_version"),
                    "restarts": env.get("restart_time", 0),
                    "uptime": (
                      env.get("pm_uptime") / 1000
                      if env.get("pm_uptime")
                      else None
                      ),
                    "cpu_percent": monit.get("cpu", 0),
                    "memory_bytes": monit.get("memory", 0),
                    "user": env.get("username"),
                    "script": env.get("pm_exec_path"),
                }
            )

        return {
            "available": True,
            "processes": output,
        }

    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "error": f"Invalid PM2 JSON: {exc}",
        }

    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "error": "PM2 command timed out",
        }

    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
        }