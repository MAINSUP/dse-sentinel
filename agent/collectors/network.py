import psutil


def get_network_info():
    counters = psutil.net_io_counters()

    interfaces = {}

    for name, stats in psutil.net_if_stats().items():
        interfaces[name] = {
            "up": stats.isup,
            "speed_mbps": stats.speed,
            "mtu": stats.mtu,
        }

    return {
        "bytes_sent": counters.bytes_sent,
        "bytes_received": counters.bytes_recv,
        "packets_sent": counters.packets_sent,
        "packets_received": counters.packets_recv,
        "interfaces": interfaces,
    }


def get_listening_ports():
    ports = []

    try:
        connections = psutil.net_connections(kind="inet")

        for connection in connections:
            if connection.status != psutil.CONN_LISTEN:
                continue

            local_address = connection.laddr

            ports.append(
                {
                    "ip": local_address.ip,
                    "port": local_address.port,
                    "pid": connection.pid,
                }
            )

    except psutil.AccessDenied:
        return {
            "available": False,
            "error": "Permission denied",
        }

    return {
        "available": True,
        "ports": ports,
    }
