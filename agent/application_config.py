APPLICATIONS = [
    {
        "name": "MIA Web",
        "type": "nextjs",
        "health_url": "http://127.0.0.1:3000",
        "public_url": "https://mia-web.dse.codes",
        "expected_status": [200],
        "timeout": 5,
        "latency_warning_ms": 1000,
    },

    {
        "name": "MIA API",
        "type": "fastapi",
        "health_url": "http://127.0.0.1:8000/health",
        "expected_status": [200],
        "timeout": 5,
        "latency_warning_ms": 1000,
    },

    {
        "name": "GitHub Webhook",
        "type": "webhook",
        "health_url": "http://127.0.0.1:9000/",
        "expected_status": [200],
        "timeout": 5,
        "latency_warning_ms": 500,
    },
]
