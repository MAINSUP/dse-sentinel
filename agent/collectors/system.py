import os
import socket
import time
import psutil

from config import DISK_PATH


def get_system_info():
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(DISK_PATH)
    load = os.getloadavg()

    boot_time = psutil.boot_time()
    uptime = time.time() - boot_time

    return {
        "hostname": socket.gethostname(),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "cpu_count": psutil.cpu_count(),
        "memory": {
            "total": memory.total,
            "used": memory.used,
            "available": memory.available,
            "percent": memory.percent,
        },
        "disk": {
            "path": DISK_PATH,
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        },
        "load_average": {
            "1m": load[0],
            "5m": load[1],
            "15m": load[2],
        },
        "uptime_seconds": uptime,
    }
