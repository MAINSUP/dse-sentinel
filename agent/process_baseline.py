import json
import os
import statistics
import time
from collections import deque
from typing import Any, Dict, Optional

import psutil


class ProcessBaselineMonitor:
    """
    Monitors a process identified by its working directory and maintains
    a persistent RSS memory baseline.

    The monitor is intentionally conservative:
      - first 24h are learning-only
      - single spikes do not trigger alerts
      - sustained growth can trigger warnings
      - process restarts are detected using create_time
    """

    STATE_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "process_baseline.json",
    )

    LEARNING_SECONDS = 24 * 60 * 60

    WARNING_MULTIPLIER = 1.35
    CRITICAL_MULTIPLIER = 1.75

    GROWTH_WINDOW_SECONDS = 60 * 60
    GROWTH_WARNING_MB = 250
    GROWTH_CRITICAL_MB = 500

    HISTORY_MAX_SECONDS = 24 * 60 * 60

    def __init__(
        self,
        name: str,
        cwd: str,
    ) -> None:
        self.name = name
        self.cwd = os.path.realpath(cwd)

        self.samples = deque()
        self.process_start_time: Optional[float] = None
        self.pid: Optional[int] = None

        self.state = "learning"
        self.state_since = time.time()

        self.learning_started_at = time.time()
        self.baseline_rss_mb: Optional[float] = None

        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not os.path.exists(self.STATE_FILE):
            return

        try:
            with open(self.STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            app = data.get(self.name)

            if not app:
                return

            self.learning_started_at = app.get(
                "learning_started_at",
                time.time(),
            )

            self.baseline_rss_mb = app.get(
                "baseline_rss_mb"
            )

            self.state = app.get(
                "state",
                "learning",
            )

            self.state_since = app.get(
                "state_since",
                time.time(),
            )

            for sample in app.get("samples", []):
                self.samples.append(sample)

        except Exception as exc:
            print(
                f"[Baseline] Failed to load state: {exc}"
            )

    def _save(self) -> None:
        try:
            all_data: Dict[str, Any] = {}

            if os.path.exists(self.STATE_FILE):
                try:
                    with open(
                        self.STATE_FILE,
                        "r",
                        encoding="utf-8",
                    ) as f:
                        all_data = json.load(f)
                except Exception:
                    all_data = {}

            all_data[self.name] = {
                "cwd": self.cwd,
                "learning_started_at": self.learning_started_at,
                "baseline_rss_mb": self.baseline_rss_mb,
                "state": self.state,
                "state_since": self.state_since,
                "samples": list(self.samples),
            }

            temp_file = self.STATE_FILE + ".tmp"

            with open(
                temp_file,
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(
                    all_data,
                    f,
                    indent=2,
                )

            os.replace(
                temp_file,
                self.STATE_FILE,
            )

        except Exception as exc:
            print(
                f"[Baseline] Failed to save state: {exc}"
            )

    # ------------------------------------------------------------------
    # Process discovery
    # ------------------------------------------------------------------

    def _find_process(self) -> Optional[psutil.Process]:
        """
        Find the exact application process.

        We require:
          1. exact working directory
          2. next-server in the command line

        This prevents Sentinel itself or another Node process from
        accidentally becoming the MIA baseline.
        """

        for proc in psutil.process_iter(
            ["pid", "name", "cmdline", "create_time"]
        ):
            try:
                info = proc.info

                pid = info["pid"]
                name = info.get("name") or ""
                cmdline = info.get("cmdline") or []

                # ------------------------------------------------------
                # Require Next.js server process
                # ------------------------------------------------------

                command = " ".join(cmdline)

                if (
                    name != "next-server"
                    and "next-server" not in command
                ):
                    continue

                # ------------------------------------------------------
                # Require exact working directory
                # ------------------------------------------------------

                process = psutil.Process(pid)

                process_cwd = os.path.realpath(
                    process.cwd()
                )

                if process_cwd != self.cwd:
                    continue

                return process

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                FileNotFoundError,
                OSError,
            ):
                continue

        return None

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def _cleanup_history(
        self,
        now: float,
    ) -> None:
        cutoff = now - self.HISTORY_MAX_SECONDS

        while self.samples:
            if self.samples[0]["timestamp"] >= cutoff:
                break

            self.samples.popleft()

    def _sample(
        self,
        process: psutil.Process,
        now: float,
    ) -> Dict[str, Any]:
        rss_mb = (
            process.memory_info().rss
            / 1024
            / 1024
        )

        cpu_percent = process.cpu_percent(
            interval=None
        )

        create_time = process.create_time()

        sample = {
            "timestamp": now,
            "pid": process.pid,
            "rss_mb": round(rss_mb, 2),
            "cpu_percent": round(cpu_percent, 2),
            "create_time": create_time,
        }

        return sample

    # ------------------------------------------------------------------
    # Baseline calculation
    # ------------------------------------------------------------------

    def _calculate_baseline(self) -> Optional[float]:
        if len(self.samples) < 20:
            return None

        values = [
            sample["rss_mb"]
            for sample in self.samples
            if "rss_mb" in sample
        ]

        if len(values) < 20:
            return None

        # Use the middle 80% to reduce the effect of extreme spikes.
        values.sort()

        trim = int(len(values) * 0.10)

        if trim > 0 and len(values) > trim * 2:
            values = values[trim:-trim]

        return round(
            statistics.median(values),
            2,
        )

    def _growth_mb(
        self,
        now: float,
        window_seconds: int,
    ) -> Optional[float]:
        cutoff = now - window_seconds

        recent = [
            s for s in self.samples
            if s["timestamp"] >= cutoff
        ]

        if len(recent) < 2:
            return None

        # Compare median of the first and last 10% of the window.
        count = max(
            1,
            len(recent) // 10,
        )

        old_values = [
            s["rss_mb"]
            for s in recent[:count]
        ]

        new_values = [
            s["rss_mb"]
            for s in recent[-count:]
        ]

        return round(
            statistics.median(new_values)
            - statistics.median(old_values),
            2,
        )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _set_state(
        self,
        new_state: str,
        now: float,
    ) -> Optional[Dict[str, Any]]:
        if new_state == self.state:
            return None

        old_state = self.state

        self.state = new_state
        self.state_since = now

        # Don't create an incident for learning -> normal.
        if old_state == "learning":
            return None

        # Recovery.
        if new_state == "normal" and old_state in (
            "warning",
            "critical",
        ):
            return {
                "id": f"process-memory-{self.name}",
                "title": (
                    f"{self.name} memory returned to normal"
                ),
                "severity": "info",
                "source": "process-baseline",
                "timestamp": now,
                "recovery": True,
            }

        # New warning/critical state.
        if new_state in (
            "warning",
            "critical",
        ):
            return {
                "id": f"process-memory-{self.name}",
                "title": (
                    f"{self.name} memory usage "
                    f"{new_state}"
                ),
                "severity": new_state,
                "source": "process-baseline",
                "timestamp": now,
            }

        return None

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------

    def update(self) -> Dict[str, Any]:
        now = time.time()

        process = self._find_process()

        if process is None:
            result = {
                "name": self.name,
                "status": "process_missing",
                "state": "critical",
                "pid": None,
                "current_rss_mb": None,
                "baseline_rss_mb": self.baseline_rss_mb,
                "growth_1h_mb": None,
                "deviation_percent": None,
                "learning_progress_percent": self._learning_progress(
                    now
                ),
            }

            self._save()

            return result

        try:
            sample = self._sample(
                process,
                now,
            )

            self.samples.append(sample)

            self._cleanup_history(now)

            self.pid = process.pid
            self.process_start_time = sample[
                "create_time"
            ]

            # ----------------------------------------------------------
            # Learning
            # ----------------------------------------------------------

            learning_elapsed = (
                now - self.learning_started_at
            )

            if (
                learning_elapsed >= self.LEARNING_SECONDS
                and self.baseline_rss_mb is None
            ):
                self.baseline_rss_mb = (
                    self._calculate_baseline()
                )

                if self.baseline_rss_mb is not None:
                    self.state = "normal"
                    self.state_since = now

                    print(
                        "[Baseline] "
                        f"{self.name} baseline established: "
                        f"{self.baseline_rss_mb:.1f} MB"
                    )

            current_rss = sample["rss_mb"]

            deviation = None

            if self.baseline_rss_mb:
                deviation = round(
                    (
                        current_rss
                        / self.baseline_rss_mb
                        - 1
                    )
                    * 100,
                    2,
                )

            growth = self._growth_mb(
                now,
                self.GROWTH_WINDOW_SECONDS,
            )

            # ----------------------------------------------------------
            # Detection
            # ----------------------------------------------------------

            incident = None

            if self.baseline_rss_mb is not None:
                critical_absolute = (
                    current_rss
                    >= self.baseline_rss_mb
                    * self.CRITICAL_MULTIPLIER
                )

                warning_absolute = (
                    current_rss
                    >= self.baseline_rss_mb
                    * self.WARNING_MULTIPLIER
                )

                critical_growth = (
                    growth is not None
                    and growth >= self.GROWTH_CRITICAL_MB
                )

                warning_growth = (
                    growth is not None
                    and growth >= self.GROWTH_WARNING_MB
                )

                if (
                    critical_absolute
                    or critical_growth
                ):
                    incident = self._set_state(
                        "critical",
                        now,
                    )

                elif (
                    warning_absolute
                    or warning_growth
                ):
                    incident = self._set_state(
                        "warning",
                        now,
                    )

                else:
                    incident = self._set_state(
                        "normal",
                        now,
                    )

            self._save()

            result = {
                "name": self.name,
                "status": "running",
                "state": self.state,
                "pid": process.pid,
                "process_start_time": self.process_start_time,
                "uptime_seconds": round(
                    now - self.process_start_time,
                    0,
                ),
                "current_rss_mb": current_rss,
                "baseline_rss_mb": self.baseline_rss_mb,
                "deviation_percent": deviation,
                "growth_1h_mb": growth,
                "learning_progress_percent": self._learning_progress(
                    now
                ),
                "samples": len(self.samples),
                "incident": incident,
            }

            return result

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            return {
                "name": self.name,
                "status": "process_missing",
                "state": "critical",
                "pid": None,
                "current_rss_mb": None,
                "baseline_rss_mb": self.baseline_rss_mb,
                "growth_1h_mb": None,
                "deviation_percent": None,
                "learning_progress_percent": self._learning_progress(
                    now
                ),
            }

    def _learning_progress(
        self,
        now: float,
    ) -> float:
        elapsed = now - self.learning_started_at

        progress = (
            elapsed
            / self.LEARNING_SECONDS
            * 100
        )

        return round(
            min(100, max(0, progress)),
            1,
        )

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "cwd": self.cwd,
            "state": self.state,
            "baseline_rss_mb": self.baseline_rss_mb,
            "samples": len(self.samples),
            "learning_progress_percent": (
                self._learning_progress(time.time())
            ),
        }
