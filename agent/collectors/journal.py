import json
import subprocess


class JournalCollector:
    def __init__(self):
        self.cursor = None

    def _run(self, args):
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            if result.returncode != 0:
                return None

            return result.stdout

        except Exception:
            return None

    def collect(self):
        """
        Return only journal entries that appeared
        since the previous collection.

        On first startup we establish a cursor and
        deliberately do NOT process historical entries.
        """

        # --------------------------------------------------
        # First run: establish current position
        # --------------------------------------------------

        if self.cursor is None:

            output = self._run(
                [
                    "journalctl",
                    "-n",
                    "1",
                    "--no-pager",
                    "-o",
                    "json",
                ]
            )

            if not output:
                return {
                    "available": False,
                    "error": "Unable to read journal",
                    "entries": [],
                }

            try:
                item = json.loads(
                    output.splitlines()[-1]
                )

                self.cursor = item.get("__CURSOR")

            except Exception as exc:
                return {
                    "available": False,
                    "error": str(exc),
                    "entries": [],
                }

            return {
                "available": True,
                "count": 0,
                "entries": [],
                "initialized": True,
            }

        # --------------------------------------------------
        # Subsequent runs: get entries after cursor
        # --------------------------------------------------

        output = self._run(
            [
                "journalctl",
                "--after-cursor",
                self.cursor,
                "--no-pager",
                "-o",
                "json",
            ]
        )

        if output is None:
            return {
                "available": False,
                "error": "Unable to query journal",
                "entries": [],
            }

        entries = []

        for line in output.splitlines():

            if not line.strip():
                continue

            try:
                item = json.loads(line)

                cursor = item.get("__CURSOR")

                if cursor:
                    self.cursor = cursor

                priority = item.get("PRIORITY")

                # We only care about errors and above.
                if priority is None:
                    continue

                if int(priority) > 3:
                    continue

                entries.append(
                    {
                        "cursor": cursor,
                        "timestamp": item.get(
                            "__REALTIME_TIMESTAMP"
                        ),
                        "hostname": item.get(
                            "_HOSTNAME"
                        ),
                        "systemd_unit": item.get(
                            "_SYSTEMD_UNIT"
                        ),
                        "syslog_identifier": item.get(
                            "SYSLOG_IDENTIFIER"
                        ),
                        "pid": item.get("_PID"),
                        "uid": item.get("_UID"),
                        "priority": priority,
                        "message": item.get(
                            "MESSAGE"
                        ),
                    }
                )

            except Exception:
                continue

        return {
            "available": True,
            "count": len(entries),
            "entries": entries,
            "initialized": False,
        }