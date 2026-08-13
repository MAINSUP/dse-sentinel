import time


class IncidentManager:
    def __init__(self):
        self.active = {}
        self.history = []

    def process(self, detections):
        events = []

        current_ids = set()

        for detection in detections:
            incident_id = detection["id"]
            current_ids.add(incident_id)

            if incident_id not in self.active:
                incident = {
                    **detection,
                    "status": "active",
                    "created_at": time.time(),
                    "last_seen": time.time(),
                    "occurrences": 1,
                }

                self.active[incident_id] = incident

                events.append({
                    "event": "created",
                    "incident": incident.copy(),
                })

            else:
                incident = self.active[incident_id]

                incident["last_seen"] = time.time()
                incident["occurrences"] += 1

        # Detect recovery
        for incident_id in list(self.active.keys()):

            if incident_id not in current_ids:

                incident = self.active.pop(incident_id)

                incident["status"] = "resolved"
                incident["resolved_at"] = time.time()
                incident["duration_seconds"] = (
                    incident["resolved_at"]
                    - incident["created_at"]
                )

                self.history.append(
                    incident.copy()
                )

                events.append({
                    "event": "resolved",
                    "incident": incident.copy(),
                })

        return events

    def get_active(self):
        return list(self.active.values())

    def get_history(self):
        return list(self.history)
