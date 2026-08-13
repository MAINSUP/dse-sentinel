import json
import time
import psutil
import socket
import threading
import subprocess
from typing import List, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from email_notifier import EmailNotifier
from dotenv import load_dotenv

from service_controls import router as service_control_router

load_dotenv()

COLLECTION_INTERVAL = 5

UNIT_MAP = {
    "Sentinel API": "sentinel-api.service",
    "Sentinel Web": "sentinel-web.service",
    "SeaVie Web": "seavie-web.service",
    "SeaVie API": "seavie-api.service",
    "MIA API": "mia-api.service",
}


def get_system_info() -> Dict[str, Any]:
    cpu_usage = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    uptime = time.time() - psutil.boot_time()
    return {
        "hostname": socket.gethostname(),
        "cpu": {"percent": cpu_usage, "count": psutil.cpu_count()},
        "memory": {"total": mem.total, "available": mem.available, "used": mem.used, "percent": mem.percent},
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free, "percent": disk.percent},
        "uptime_seconds": uptime,
    }


def get_top_processes(limit: int = 10) -> List[Dict[str, Any]]:
    procs = []
    for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
        try:
            p = proc.info
            procs.append({"pid": p['pid'], "name": p['name'], "user": p['username'], "cpu_percent": p['cpu_percent'], "memory_percent": round(p['memory_percent'] or 0.0, 2)})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    procs.sort(key=lambda x: (x['cpu_percent'] or 0, x['memory_percent'] or 0), reverse=True)
    return procs[:limit]


def get_systemd_services() -> List[Dict[str, Any]]:
    services = []
    try:
        output = subprocess.check_output(["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"], text=True)
        for line in output.strip().splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 4:
                unit, load, active, sub = parts[:4]
                services.append({"name": unit, "load": load, "active_state": active, "sub_state": sub, "description": parts[4] if len(parts) > 4 else "", "status": "running" if active == "active" else "failed" if active == "failed" else "stopped"})
    except Exception as exc:
        print(f"[Collector Error] systemd: {exc}")
    return services


def get_pm2_processes() -> List[Dict[str, Any]]:
    try:
        output = subprocess.check_output(["pm2", "jlist"], text=True)
        return [{"name": p.get("name"), "pm_id": p.get("pm_id"), "status": p.get("pm2_env", {}).get("status"), "cpu": p.get("monit", {}).get("cpu"), "memory": p.get("monit", {}).get("memory"), "restarts": p.get("pm2_env", {}).get("restart_time")} for p in json.loads(output)]
    except Exception:
        return []


def get_network_info() -> Dict[str, Any]:
    n = psutil.net_io_counters()
    return {"bytes_sent": n.bytes_sent, "bytes_recv": n.bytes_recv, "packets_sent": n.packets_sent, "packets_recv": n.packets_recv}


def get_listening_ports() -> List[Dict[str, Any]]:
    result = []
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == psutil.CONN_LISTEN:
                name = ""
                if conn.pid:
                    try: name = psutil.Process(conn.pid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied): pass
                result.append({"port": conn.laddr.port, "ip": conn.laddr.ip, "address": f"{conn.laddr.ip}:{conn.laddr.port}", "pid": conn.pid, "process_name": name})
    except Exception as exc:
        print(f"[Collector Error] ports: {exc}")
    return result


def collect_applications() -> List[Dict[str, Any]]:
    apps = []
    for display_name, unit in UNIT_MAP.items():
        app = {"name": display_name, "unit": unit, "status": "unknown", "active_state": "unknown", "sub_state": "unknown", "pid": None, "restarts": 0}
        try:
            output = subprocess.check_output(["systemctl", "show", unit, "--property=ActiveState,SubState,MainPID,NRestarts"], text=True)
            props = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
            app["active_state"] = props.get("ActiveState", "unknown")
            app["sub_state"] = props.get("SubState", "unknown")
            app["pid"] = int(props.get("MainPID", 0))
            app["restarts"] = int(props.get("NRestarts", 0))
            app["status"] = "healthy" if app["active_state"] == "active" else "failed" if app["active_state"] == "failed" else "stopped"
        except Exception:
            app["status"] = "error"
        apps.append(app)
    return apps


def collect_deployment_state() -> Dict[str, Any]:
    return {"status": "synced", "last_check": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


class JournalCollector:
    def collect(self, lines: int = 50) -> Dict[str, Any]:
        try:
            output = subprocess.check_output(["journalctl", "-p", "3", "-n", str(lines), "--no-pager", "-o", "json"], text=True)
            entries = [json.loads(line) for line in output.splitlines() if line]
            return {"errors_count": len(entries), "entries": entries}
        except Exception:
            return {"errors_count": 0, "entries": []}


class DetectionEngine:
    def check_systemd_services(self, services):
        return [{"id": f"systemd-{s['name']}", "title": f"Service Failed: {s['name']}", "severity": "critical", "source": "systemd", "timestamp": time.time()} for s in services if s.get("status") == "failed"]

    def check_pm2_processes(self, processes):
        return [{"id": f"pm2-{p['name']}", "title": f"PM2 Process Issue: {p['name']}", "severity": "warning", "source": "pm2", "timestamp": time.time()} for p in processes if p.get("status") in ["errored", "stopped"]]


class IncidentManager:
    def __init__(self):
        self.active_incidents = {}
        self.history = []

    def process(self, detections):
        current_ids = {d["id"] for d in detections}
        for incident_id in list(self.active_incidents):
            if incident_id not in current_ids:
                item = self.active_incidents.pop(incident_id)
                item["resolved_at"] = time.time()
                self.history.append(item)
        for detection in detections:
            self.active_incidents.setdefault(detection["id"], detection)
        return list(self.active_incidents.values())

    def get_active(self): return list(self.active_incidents.values())
    def get_history(self): return self.history


incident_manager = IncidentManager()
email_notifier = EmailNotifier()
latest_agent_data = {}


def run_agent_loop():
    global latest_agent_data
    detector = DetectionEngine()
    journal = JournalCollector()
    while True:
        try:
            systemd = get_systemd_services()
            pm2 = get_pm2_processes()
            apps = collect_applications()
            detections = detector.check_systemd_services(systemd) + detector.check_pm2_processes(pm2)
            previous = set(incident_manager.active_incidents)
            events = incident_manager.process(detections)
            for incident in events:
                if incident.get("id") not in previous:
                    email_notifier.send_incident(incident)
            latest_agent_data = {"active_incidents": incident_manager.get_active(), "events": events, "history": incident_manager.get_history(), "journal": journal.collect(), "applications": apps}
        except Exception as exc:
            print(f"[Sentinel Background Agent Error] {exc}")
        time.sleep(COLLECTION_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=run_agent_loop, daemon=True).start()
    yield


app = FastAPI(title="DSE Sentinel API", version="0.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(service_control_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "dse-sentinel-api"}

@app.get("/api/system")
def system(): return get_system_info()

@app.get("/api/processes")
def processes(): return get_top_processes()

@app.get("/api/services")
def services(): return {"systemd": get_systemd_services(), "pm2": get_pm2_processes()}

@app.get("/api/network")
def network(): return {"network": get_network_info(), "listening_ports": get_listening_ports()}

@app.post("/api/test-email")
def test_email():
    incident = {"id": "manual-email-test", "title": "Sentinel Email Test", "severity": "critical", "source": "manual", "timestamp": time.time()}
    return {"success": email_notifier.send_incident(incident)}

@app.get("/api/applications")
def applications(): return latest_agent_data.get("applications") or collect_applications()

@app.get("/api/deployments")
def deployments(): return collect_deployment_state()

@app.get("/api/overview")
def overview():
    return {
        "system": get_system_info(),
        "applications": latest_agent_data.get("applications") or collect_applications(),
        "deployments": collect_deployment_state(),
        "services": {"systemd": get_systemd_services(), "pm2": get_pm2_processes()},
        "network": {"listening_ports": get_listening_ports()},
        "listening_ports": get_listening_ports(),
        "incidents": {"active": latest_agent_data.get("active_incidents", []), "events": latest_agent_data.get("events", []), "history": latest_agent_data.get("history", [])},
        "journal": latest_agent_data.get("journal", {}),
    }

@app.get("/api/services/{service_name}/logs")
def get_service_logs(service_name: str, lines: int = 50):
    clean = "".join(c for c in service_name if c.isalnum() or c in "._-")
    try:
        output = subprocess.check_output(["journalctl", "-u", clean, "-n", str(lines), "--no-pager"], text=True, stderr=subprocess.STDOUT)
        return {"service": clean, "logs": output.splitlines()}
    except Exception as exc:
        return {"service": clean, "error": str(exc), "logs": []}

@app.get("/api/services/{service_name}/stats")
def get_service_stats(service_name: str):
    clean = "".join(c for c in service_name if c.isalnum() or c in "._-")
    try:
        output = subprocess.check_output(["systemctl", "show", clean, "--property=NRestarts,ActiveState,SubState,MainPID,ExecMainStatus"], text=True)
        props = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        return {"service": clean, "restarts_crashes": int(props.get("NRestarts", 0)), "active_state": props.get("ActiveState", "unknown"), "sub_state": props.get("SubState", "unknown"), "main_pid": props.get("MainPID", "0")}
    except Exception as exc:
        return {"service": clean, "error": str(exc), "restarts_crashes": 0}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
