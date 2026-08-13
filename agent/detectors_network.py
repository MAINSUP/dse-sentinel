from config import (
    EXPECTED_PUBLIC_PORTS,
    EXPECTED_PRIVATE_PORTS,
)


def is_public_ip(ip):
    return ip in (
        "0.0.0.0",
        "::",
    )


def check_listening_ports(port_data):
    events = []

    if not port_data.get("available"):
        return events

    seen_ports = set()

    for port_info in port_data.get("ports", []):
        ip = port_info.get("ip")
        port = port_info.get("port")
        pid = port_info.get("pid")

        if not is_public_ip(ip):
            continue

        # Avoid duplicate IPv4/IPv6 findings
        # for the same port.
        if port in seen_ports:
            continue

        seen_ports.add(port)

        # --------------------------------------------------
        # Expected private port exposed publicly
        # --------------------------------------------------

        if port in EXPECTED_PRIVATE_PORTS:
            expected = EXPECTED_PRIVATE_PORTS[port]

            events.append(
                {
                    "id": f"network:private-port-exposed:{port}",
                    "severity": "high",
                    "type": "private_port_exposed",
                    "title": (
                        f"Private service publicly exposed: "
                        f"{port}"
                    ),
                    "description": (
                        f"{expected['service']} is listening "
                        f"on {ip}:{port}, but this port is "
                        f"configured as localhost-only."
                    ),
                    "metadata": {
                        "ip": ip,
                        "port": port,
                        "pid": pid,
                        "service": expected["service"],
                        "reason": expected["reason"],
                        "expected": "localhost",
                    },
                }
            )

            continue

        # --------------------------------------------------
        # Unexpected public port
        # --------------------------------------------------

        if port not in EXPECTED_PUBLIC_PORTS:
            events.append(
                {
                    "id": (
                        f"network:"
                        f"unexpected-public-port:"
                        f"{port}"
                    ),
                    "severity": "high",
                    "type": "unexpected_public_port",
                    "title": (
                        f"Unexpected public port: {port}"
                    ),
                    "description": (
                        f"Port {port} is listening on "
                        f"{ip} and is not present in "
                        f"Sentinel's approved public-port "
                        f"configuration."
                    ),
                    "metadata": {
                        "ip": ip,
                        "port": port,
                        "pid": pid,
                        "expected": "not exposed",
                    },
                }
            )

    return events