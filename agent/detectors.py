import time


class DetectionEngine:
    def __init__(self):
        self.active_incidents = {}
        self.previous_pm2_restarts = {}

    def create_incident(
        self,
        incident_id,
        severity,
        title,
        description,
        metadata=None,
    ):
        if incident_id in self.active_incidents:
            return None

        incident = {
            "id": incident_id,
            "severity": severity,
            "title": title,
            "description": description,
            "metadata": metadata or {},
            "status": "active",
            "created_at": time.time(),
        }

        self.active_incidents[incident_id] = incident

        return incident

    def resolve_incident(self, incident_id):
        incident = self.active_incidents.pop(
            incident_id,
            None,
        )

        if incident is None:
            return None

        incident["status"] = "resolved"
        incident["resolved_at"] = time.time()

        return incident

    def check_systemd_services(self, services):
        events = []

        for service in services:
            name = service["name"]
            status = service["status"]
            running = service["running"]

            incident_id = f"systemd:{name}"

            if not running:
                incident = self.create_incident(
                    incident_id=incident_id,
                    severity="critical",
                    title=f"Service failure: {name}",
                    description=(
                        f"Systemd service '{name}' "
                        f"is not running. "
                        f"Current status: {status}"
                    ),
                    metadata={
                        "service": name,
                        "status": status,
                    },
                )

                if incident:
                    events.append(incident)

            else:
                resolved = self.resolve_incident(
                    incident_id
                )

                if resolved:
                    events.append(resolved)

        return events

    def check_pm2_processes(self, pm2_data):
        events = []

        if not pm2_data.get("available"):
            return events

        for process in pm2_data.get(
            "processes",
            [],
        ):
            name = process.get("name")
            status = process.get("status")

            incident_id = f"pm2:{name}"

            if status not in ("online", "launching"):
                incident = self.create_incident(
                    incident_id=incident_id,
                    severity="critical",
                    title=f"PM2 application failure: {name}",
                    description=(
                        f"PM2 application '{name}' "
                        f"is not healthy. "
                        f"Current status: {status}"
                    ),
                    metadata={
                        "application": name,
                        "pid": process.get("pid"),
                        "status": status,
                        "restarts": process.get(
                            "restarts",
                            0,
                        ),
                    },
                )

                if incident:
                    events.append(incident)

            else:
                resolved = self.resolve_incident(
                    incident_id
                )

                if resolved:
                    events.append(resolved)

        return events

    def get_active_incidents(self):
        return list(
            self.active_incidents.values()
        )
