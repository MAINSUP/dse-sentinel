HOSTNAME = None

COLLECTION_INTERVAL = 10

WATCHED_SERVICES = [
    "nginx",
    "ssh",
]

# Empty = monitor all PM2 applications
WATCHED_PM2 = []

TOP_PROCESSES = 10

DISK_PATH = "/"

# Detection thresholds
PM2_RESTART_THRESHOLD = 3
PM2_RESTART_WINDOW_SECONDS = 300

# --------------------------------------------------
# Network security
# --------------------------------------------------

# Ports intentionally exposed to the Internet.
EXPECTED_PUBLIC_PORTS = {
    22: {
        "service": "SSH",
        "reason": "Remote administration",
    },
    80: {
        "service": "HTTP",
        "reason": "Web traffic",
    },
    443: {
        "service": "HTTPS",
        "reason": "Secure web traffic",
    },
    9000: {
        "service": "GitHub webhook",
        "reason": "GitHub webhook listener",
    },
}

# Ports that should only listen on localhost.
EXPECTED_PRIVATE_PORTS = {
    3000: {
        "service": "Next.js",
        "reason": "Application server behind Nginx",
    },
    8000: {
        "service": "API",
        "reason": "Internal API",
    },
    8001: {
        "service": "API",
        "reason": "Internal API",
    },
     8002: {
        "service": "API",
        "reason": "Internal API",
    },
    8080: {
        "service": "Internal service",
        "reason": "Local service",
    },
}