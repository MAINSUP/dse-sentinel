import psutil

from config import TOP_PROCESSES


def get_top_processes():
    processes = []

    for process in psutil.process_iter(
        [
            "pid",
            "name",
            "username",
            "status",
            "cpu_percent",
            "memory_percent",
            "create_time",
        ]
    ):
        try:
            info = process.info

            processes.append(
                {
                    "pid": info["pid"],
                    "name": info["name"],
                    "username": info["username"],
                    "status": info["status"],
                    "cpu_percent": info["cpu_percent"],
                    "memory_percent": info["memory_percent"],
                    "create_time": info["create_time"],
                }
            )

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            continue

    processes.sort(
        key=lambda p: p["memory_percent"],
        reverse=True,
    )

    return processes[:TOP_PROCESSES]
