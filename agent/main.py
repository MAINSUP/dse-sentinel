import os
import json
import time
import psutil
import socket
import threading
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from email_notifier import EmailNotifier
# ==========================================
# CONFIGURATION
# ==========================================
COLLECTION_INTERVAL = 5  # Collection cycle in seconds

# Map of service names / display labels to actual systemd unit names
UNIT_MAP = {
    "Sentinel API": "sentinel-api.service",
    "Sentinel Web": "sentinel-web.service",
    "SeaVie Web": "seavie-web.service",
    "SeaVie API": "seavie-api.service",
}

# ==========================================
# COLLECTORS
# ==========================================
def get_system_info() -> Dict[str, Any]:
    """Collects host-level system metrics (CPU, Memory, Disk)."""
    cpu_usage = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    boot_time = psutil.boot_time()
    uptime = time.time() - boot_time

    return {
        "hostname": socket.gethostname(),
        "cpu": {
            "percent": cpu_usage,
            "count": psutil.cpu_count(),
        },
        "memory": {
            "total": mem.total,
            "available": mem.available,
            "used": mem.used,
            "percent": mem.percent,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        },
        "uptime_seconds": uptime,
    }


def get_top_processes(limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieves high resource-consuming processes running on the machine."""
    procs = []
    for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
        try:
            pinfo = proc.info
            procs.append({
                "pid": pinfo['pid'],
                "name": pinfo['name'],
                "user": pinfo['username'],
                "cpu_percent": pinfo['cpu_percent'],
                "memory_percent": round(pinfo['memory_percent'] or 0.0, 2),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    procs.sort(key=lambda x: (x['cpu_percent'] or 0, x['memory_percent'] or 0), reverse=True)
    return procs[:limit]


def get_systemd_services() -> List[Dict[str, Any]]:
    """Fetches systemd unit statuses via systemctl."""
    services = []
    try:
        cmd = ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"]
        output = subprocess.check_output(cmd, text=True)
        
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split(None, 4)
            if len(parts) >= 4:
                unit = parts[0]
                load = parts[1]
                active = parts[2]
                sub = parts[3]
                desc = parts[4] if len(parts) > 4 else ""
                
                services.append({
                    "name": unit,
                    "load": load,
                    "active_state": active,
                    "sub_state": sub,
                    "description": desc,
                    "status": "running" if active == "active" else "failed" if active == "failed" else "stopped"
                })
    except Exception as exc:
        print(f"[Collector Error] systemd services check failed: {exc}")
    return services


def get_pm2_processes() -> List[Dict[str, Any]]:
    """Retrieves PM2 managed process states if PM2 is present."""
    try:
        cmd = ["pm2", "jlist"]
        output = subprocess.check_output(cmd, text=True)
        data = json.loads(output)
        processes = []
        for p in data:
            processes.append({
                "name": p.get("name"),
                "pm_id": p.get("pm_id"),
                "status": p.get("pm2_env", {}).get("status"),
                "cpu": p.get("monit", {}).get("cpu"),
                "memory": p.get("monit", {}).get("memory"),
                "restarts": p.get("pm2_env", {}).get("restart_time"),
            })
        return processes
    except Exception:
        return []


def get_network_info() -> Dict[str, Any]:
    """Retrieves general network counters."""
    net_io = psutil.net_io_counters()
    return {
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
        "packets_sent": net_io.packets_sent,
        "packets_recv": net_io.packets_recv,
    }


def get_listening_ports() -> List[Dict[str, Any]]:
    """Retrieves active network listening ports on the host."""
    listening = []
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == psutil.CONN_LISTEN:
                laddr = f"{conn.laddr.ip}:{conn.laddr.port}"
                proc_name = ""
                if conn.pid:
                    try:
                        proc_name = psutil.Process(conn.pid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                listening.append({
                    "port": conn.laddr.port,
                    "ip": conn.laddr.ip,
                    "address": laddr,
                    "pid": conn.pid,
                    "process_name": proc_name
                })
    except Exception as exc:
        print(f"[Collector Error] listening ports check failed: {exc}")
    return listening


def collect_applications() -> List[Dict[str, Any]]:
    """Collects mapped key application/service information."""
    apps = []
    for display_name, unit_name in UNIT_MAP.items():
        app_data = {
            "name": display_name,
            "unit": unit_name,
            "status": "unknown",
            "active_state": "unknown",
            "sub_state": "unknown",
            "pid": None,
            "restarts": 0
        }
        try:
            cmd = ["systemctl", "show", unit_name, "--property=ActiveState,SubState,MainPID,NRestarts"]
            output = subprocess.check_output(cmd, text=True)
            props = dict(line.split("=", 1) for line in output.strip().split("\n") if "=" in line)
            
            app_data["active_state"] = props.get("ActiveState", "unknown")
            app_data["sub_state"] = props.get("SubState", "unknown")
            app_data["pid"] = int(props.get("MainPID", 0))
            app_data["restarts"] = int(props.get("NRestarts", 0))
            
            if app_data["active_state"] == "active":
                app_data["status"] = "healthy"
            elif app_data["active_state"] == "failed":
                app_data["status"] = "failed"
            else:
                app_data["status"] = "stopped"
        except Exception:
            app_data["status"] = "error"
            
        apps.append(app_data)
    return apps


def collect_deployment_state() -> Dict[str, Any]:
    """Retrieves deployment state metadata."""
    return {
        "status": "synced",
        "last_check": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


class JournalCollector:
    """Collects recent log entries from systemd journal."""
    def collect(self, lines: int = 50) -> Dict[str, Any]:
        try:
            cmd = ["journalctl", "-p", "3", "-n", str(lines), "--no-pager", "-o", "json"]
            output = subprocess.check_output(cmd, text=True)
            entries = [json.loads(line) for line in output.strip().split("\n") if line]
            return {"errors_count": len(entries), "entries": entries}
        except Exception:
            return {"errors_count": 0, "entries": []}


# ==========================================
# DETECTORS & INCIDENT MANAGEMENT
# ==========================================
class DetectionEngine:
    def check_systemd_services(self, services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        events = []
        for svc in services:
            if svc.get("status") == "failed":
                events.append({
                    "id": f"systemd-{svc['name']}",
                    "title": f"Service Failed: {svc['name']}",
                    "severity": "critical",
                    "source": "systemd",
                    "timestamp": time.time(),
                })
        return events

    def check_pm2_processes(self, processes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        events = []
        for proc in processes:
            if proc.get("status") in ["errored", "stopped"]:
                events.append({
                    "id": f"pm2-{proc['name']}",
                    "title": f"PM2 Process Issue: {proc['name']}",
                    "severity": "warning",
                    "source": "pm2",
                    "timestamp": time.time(),
                })
        return events


def check_listening_ports(ports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return []


def check_journal_errors(journal: Dict[str, Any]) -> List[Dict[str, Any]]:
    events = []
    if journal.get("errors_count", 0) > 10:
        events.append({
            "id": "journal-high-errors",
            "title": "High system log error frequency detected",
            "severity": "warning",
            "source": "journalctl",
            "timestamp": time.time(),
        })
    return events


def detect_application_failures(apps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    events = []
    for app in apps:
        if app.get("status") == "failed":
            events.append({
                "id": f"app-{app['name']}",
                "title": f"Application Failure: {app['name']}",
                "severity": "critical",
                "source": "application",
                "timestamp": time.time(),
            })
    return events


class IncidentManager:
    """Manages active incidents and keeps a record of resolved ones."""
    def __init__(self):
        self.active_incidents = {}
        self.history = []

    def process(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        current_ids = {d["id"] for d in detections}
        
        # Resolve cleared incidents
        for inc_id in list(self.active_incidents.keys()):
            if inc_id not in current_ids:
                resolved_inc = self.active_incidents.pop(inc_id)
                resolved_inc["resolved_at"] = time.time()
                self.history.append(resolved_inc)

        # Add or update current incidents
        for det in detections:
            if det["id"] not in self.active_incidents:
                self.active_incidents[det["id"]] = det

        return list(self.active_incidents.values())

    def get_active(self) -> List[Dict[str, Any]]:
        return list(self.active_incidents.values())

    def get_history(self) -> List[Dict[str, Any]]:
        return self.history


# ==========================================
# SHARED STATE & BACKGROUND WORKER
# ==========================================
incident_manager = IncidentManager()
email_notifier = EmailNotifier()
latest_agent_data = {}


def run_agent_loop():
    """Background thread loop running detections every COLLECTION_INTERVAL seconds."""
    global latest_agent_data
    detector = DetectionEngine()
    journal_collector = JournalCollector()

    print("[Sentinel Background Agent] Daemon thread started successfully.")

    while True:
        try:
            # 1. Collect raw states
            systemd_svcs = get_systemd_services()
            pm2_svcs = get_pm2_processes()
            ports = get_listening_ports()
            journal = journal_collector.collect()
            apps = collect_applications()

            # 2. Run detections
            systemd_events = detector.check_systemd_services(systemd_svcs)
            pm2_events = detector.check_pm2_processes(pm2_svcs)
            network_events = check_listening_ports(ports)
            journal_events = check_journal_errors(journal)
            app_events = detect_application_failures(apps)

            # 3. Process incidents
            detections = (
             systemd_events
             + pm2_events
             + network_events
             + journal_events
             + app_events
             )

            # Remember incidents that were already active.
            previous_incident_ids = set(
              incident_manager.active_incidents.keys()
            )

            incident_events = incident_manager.process(detections)

             # Send email only for newly created incidents.
             # This prevents Sentinel from sending the same email
              # every 5-second collection cycle.
            for incident in incident_events:
                incident_id = incident.get("id")

                if incident_id not in previous_incident_ids:
                   email_notifier.send_incident(incident)

            # 4. Update shared memory atomically
            latest_agent_data = {
                "active_incidents": incident_manager.get_active(),
                "events": incident_events,
                "history": incident_manager.get_history(),
                "journal": journal,
                "applications": apps,
            }
        except Exception as err:
            print(f"[Sentinel Background Agent Error] {err}")

        # Use standard thread sleep (NOT asyncio.sleep)
        time.sleep(COLLECTION_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Launch agent thread
    agent_thread = threading.Thread(target=run_agent_loop, daemon=True)
    agent_thread.start()
    yield
    # Shutdown logic if any
    print("[Sentinel API] Shutting down.")


# ==========================================
# FASTAPI APPLICATION & ROUTING
# ==========================================
app = FastAPI(
    title="DSE Sentinel API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "dse-sentinel-api",
    }


@app.get("/api/system")
def system():
    return get_system_info()


@app.get("/api/processes")
def processes():
    return get_top_processes()


@app.get("/api/services")
def services():
    return {
        "systemd": get_systemd_services(),
        "pm2": get_pm2_processes(),
    }


@app.get("/api/network")
def network():
    return {
        "network": get_network_info(),
        "listening_ports": get_listening_ports(),
    }


@app.get("/api/applications")
def applications():
    return latest_agent_data.get("applications") or collect_applications()


@app.get("/api/deployments")
def deployments():
    return collect_deployment_state()


@app.get("/api/overview")
def overview():
    sys_info = get_system_info()
    apps_info = latest_agent_data.get("applications") or collect_applications()
    systemd_svcs = get_systemd_services()
    pm2_svcs = get_pm2_processes()
    listening = get_listening_ports()

    return {
        "system": sys_info,
        "applications": apps_info,
        "deployments": collect_deployment_state(),
        "services": {
            "systemd": systemd_svcs,
            "pm2": pm2_svcs,
        },
        "network": {
            "listening_ports": listening,
        },
        # Pass listening directly at the root of overview for frontend compatibility:
        "listening_ports": listening,
        "incidents": {
            "active": latest_agent_data.get("active_incidents", []),
            "events": latest_agent_data.get("events", []),
            "history": latest_agent_data.get("history", []),
        },
        "journal": latest_agent_data.get("journal", {}),
    }


# ==========================================
# DRILL-DOWN ENDPOINTS
# ==========================================

@app.get("/api/services/{service_name}/logs")
def get_service_logs(service_name: str, lines: int = 50):
    clean_name = "".join(c for c in service_name if c.isalnum() or c in "._-")
    try:
        cmd = ["journalctl", "-u", clean_name, "-n", str(lines), "--no-pager"]
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
        return {
            "service": clean_name,
            "logs": [line for line in output.strip().split("\n") if line],
        }
    except Exception as exc:
        return {"service": clean_name, "error": str(exc), "logs": []}


@app.get("/api/services/{service_name}/stats")
def get_service_stats(service_name: str):
    clean_name = "".join(c for c in service_name if c.isalnum() or c in "._-")
    try:
        cmd = [
            "systemctl",
            "show",
            clean_name,
            "--property=NRestarts,ActiveState,SubState,MainPID,ExecMainStatus",
        ]
        output = subprocess.check_output(cmd, text=True)
        props = dict(
            line.split("=", 1) for line in output.strip().split("\n") if "=" in line
        )
        return {
            "service": clean_name,
            "restarts_crashes": int(props.get("NRestarts", 0)),
            "active_state": props.get("ActiveState", "unknown"),
            "sub_state": props.get("SubState", "unknown"),
            "main_pid": props.get("MainPID", "0"),
        }
    except Exception as exc:
        return {"service": clean_name, "error": str(exc), "restarts_crashes": 0}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)