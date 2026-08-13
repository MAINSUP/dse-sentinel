APPLICATIONS = [
    {
        "name": "MIA Web",
        "type": "nextjs",
        "url": "http://127.0.0.1:3000",
        "expected_status": [200],
        "timeout": 5,
        "latency_warning_ms": 1000,
    },

    {
        "name": "MIA Web HTTPS",
        "type": "web",
        "url": "https://mia-web.dse.codes",
        "expected_status": [200],
        "timeout": 10,
        "latency_warning_ms": 1500,
    },

    # Add your actual FastAPI health endpoints here.
    #
    # Example:
    #
    # {
    #     "name": "MIA API",
    #     "type": "fastapi",
    #     "url": "http://127.0.0.1:8000/health",
    #     "expected_status": [200],
    #     "timeout": 5,
    #     "latency_warning_ms": 1000,
    # },

    # Your webhook should eventually get a dedicated
    # synthetic check. For now we monitor the listener.
    {
        "name": "GitHub Webhook",
        "type": "webhook",
        "url": "http://127.0.0.1:9000/health",
        "expected_status": [200],
        "timeout": 5,
        "latency_warning_ms": 1000,
    },
]
