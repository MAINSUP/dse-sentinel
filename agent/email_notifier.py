import os
import socket
from typing import Any, Dict

import requests


RESEND_API_URL = "https://api.resend.com/emails"


class EmailNotifier:
    """Sends Sentinel incident notifications through Resend."""

    def __init__(self) -> None:
        self.api_key = os.getenv("RESEND_API_KEY")

        self.from_email = os.getenv(
            "SENTINEL_EMAIL_FROM",
            "Sentinel <sentinel@dse.codes>",
        )

        self.to_email = os.getenv(
            "SENTINEL_EMAIL_TO",
            "sentinel@dse.codes",
        )

        self.hostname = (
            os.getenv("SENTINEL_HOSTNAME")
            or socket.gethostname()
        )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.to_email)

    def send_incident(self, incident: Dict[str, Any]) -> bool:
        if not self.enabled:
            print("[Sentinel Email] Email notifications disabled")
            return False

        severity = str(
            incident.get("severity", "unknown")
        ).upper()

        title = incident.get(
            "title",
            "Sentinel incident",
        )

        source = incident.get(
            "source",
            "unknown",
        )

        incident_id = incident.get(
            "id",
            "unknown",
        )

        subject = (
            f"[SENTINEL][{severity}] "
            f"{title} on {self.hostname}"
        )

        text = "\n".join([
            "DSE Sentinel detected a new incident.",
            "",
            f"Host: {self.hostname}",
            f"Incident: {incident_id}",
            f"Severity: {severity}",
            f"Source: {source}",
            f"Title: {title}",
            f"Timestamp: {incident.get('timestamp', 'unknown')}",
            "",
            "This notification was generated automatically "
            "by DSE Sentinel.",
        ])

        payload = {
            "from": self.from_email,
            "to": [self.to_email],
            "subject": subject,
            "text": text,
        }

        try:
            response = requests.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
            )

            response.raise_for_status()

            print(
                f"[Sentinel Email] "
                f"Incident notification sent: {incident_id}"
            )

            return True

        except requests.RequestException as exc:
            print(
                f"[Sentinel Email Error] "
                f"Failed to send {incident_id}: {exc}"
            )

            return False
