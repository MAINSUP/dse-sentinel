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
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from email_notifier import EmailNotifier
from dotenv import load_dotenv
from process_baseline import ProcessBaselineMonitor

load_dotenv()

COLLECTION_INTERVAL = 5

UNIT_MAP = {
    "Sentinel API": "dse-sentinel-api.service",
    "Sentinel Web": "sentinel-web.service",
    #"SeaVie Web": "seavie-web.service",
    "SeaVie API": "seavie-api.service",
    "MIA Web": "mia-web",
    "MIA API":"mia-api.service",
}

CONTROLLED_SERVICES = {
    "MIA Web": {"type": "pm2", "pm2_name": "mia-web"},
    "MIA API": {
        "type": "systemd",
        "unit": "mia-api.service",
    },
    "SeaVie API": {
        "type": "systemd",
        "unit": "seavie-api.service",
    },
  #  "SeaVie Web": {"type": "pm2", "pm2_name": "seavie-web"},
    "Sentinel API": {
    "type": "systemd",
    "unit": "dse-sentinel-api.service",
},
    "Sentinel Web": {"type": "systemd", 
    "unit": "sentinel-web.service"
    },
    
  "VS Code Console":
  {"type": "systemd",
  "unit": "code-server.service",
},
}

MOBILE_APPS = {
    "MIA Mobile": {
        "project_dir": "/home/mainsup/projects/MIA/mobile",

        "build_command": [
            "eas",
            "build",
            "--platform",
            "all",
            "--profile",
            "production",
            "--non-interactive",
        ],

        "deploy_command": [
            "eas",
            "build",
            "--platform",
            "all",
            "--profile",
            "production",
            "--auto-submit",
            "--non-interactive",
        ],
    },
}

mobile_jobs = {}
mobile_jobs_lock = threading.Lock()


def run_mobile_job(job_id: str, app_name: str, deploy: bool):
    app = MOBILE_APPS[app_name]

    command = (
        app["deploy_command"]
        if deploy
        else app["build_command"]
    )

    with mobile_jobs_lock:
        mobile_jobs[job_id]["status"] = "running"
        mobile_jobs[job_id]["command"] = " ".join(command)

    try:
        result = subprocess.run(
            command,
            cwd=app["project_dir"],
            capture_output=True,
            text=True,
            timeout=7200,
            check=False,
            env={
                **os.environ,
                "CI": "1",
            },
        )

        with mobile_jobs_lock:
            mobile_jobs[job_id].update({
                "status": (
                    "success"
                    if result.returncode == 0
                    else "failed"
                ),
                "return_code": result.returncode,
                "finished_at": time.time(),
                "stdout": result.stdout[-15000:],
                "stderr": result.stderr[-15000:],
            })

    except subprocess.TimeoutExpired:
        with mobile_jobs_lock:
            mobile_jobs[job_id].update({
                "status": "timeout",
                "finished_at": time.time(),
                "error": "EAS build timed out after 2 hours",
            })

    except Exception as exc:
        with mobile_jobs_lock:
            mobile_jobs[job_id].update({
                "status": "failed",
                "finished_at": time.time(),
                "error": str(exc),
            })


def get_system_info() -> Dict[str, Any]:
    cpu_usage = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    uptime = time.time() - psutil.boot_time()
    return {
        "hostname": socket.gethostname(),
        "cpu": {"percent": cpu_usage, "count": psutil.cpu_count()},
        "memory": {
            "total": mem.total, "available": mem.available,
            "used": mem.used, "percent": mem.percent,
        },
        "disk": {
            "total": disk.total, "used": disk.used,
            "free": disk.free, "percent": disk.percent,
        },
        "uptime_seconds": uptime,
    }


def get_top_processes(limit: int = 10) -> List[Dict[str, Any]]:
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
    services = []
    try:
        output = subprocess.check_output(
            ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"],
            text=True,
        )
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split(None, 4)
            if len(parts) >= 4:
                unit, load, active, sub = parts[:4]
                desc = parts[4] if len(parts) > 4 else ""
                services.append({
                    "name": unit,
                    "load": load,
                    "active_state": active,
                    "sub_state": sub,
                    "description": desc,
                    "status": "running" if active == "active" else "failed" if active == "failed" else "stopped",
                })
    except Exception as exc:
        print(f"[Collector Error] systemd services check failed: {exc}")
    return services


def get_pm2_processes() -> List[Dict[str, Any]]:
    try:
        output = subprocess.check_output(["/home/mainsup/.nvm/versions/node/v24.18.1/bin/pm2", "jlist"], text=True)
        data = json.loads(output)
        return [{
            "name": p.get("name"),
            "pm_id": p.get("pm_id"),
            "status": p.get("pm2_env", {}).get("status"),
            "cpu": p.get("monit", {}).get("cpu"),
            "memory": p.get("monit", {}).get("memory"),
            "restarts": p.get("pm2_env", {}).get("restart_time"),
        } for p in data]
    except Exception:
        return []


def get_network_info() -> Dict[str, Any]:
    net_io = psutil.net_io_counters()
    return {
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
        "packets_sent": net_io.packets_sent,
        "packets_recv": net_io.packets_recv,
    }


def get_listening_ports() -> List[Dict[str, Any]]:
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
                    "process_name": proc_name,
                })
    except Exception as exc:
        print(f"[Collector Error] listening ports check failed: {exc}")
    return listening


def collect_applications() -> List[Dict[str, Any]]:
    apps = []
    for display_name, unit_name in UNIT_MAP.items():
        app_data = {
            "name": display_name, "unit": unit_name, "status": "unknown",
            "active_state": "unknown", "sub_state": "unknown", "pid": None, "restarts": 0,
        }
        try:
            output = subprocess.check_output(
                ["systemctl", "show", unit_name, "--property=ActiveState,SubState,MainPID,NRestarts"],
                text=True,
            )
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
    return {
        "status": "synced",
        "last_check": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def run_controlled_service(service_name: str, action: str) -> Dict[str, Any]:
    """
    Execute a strictly allow-listed service control action.
    Never pass arbitrary user input to a shell.
    """
    service = CONTROLLED_SERVICES.get(service_name)

    if not service:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown controlled service: {service_name}",
        )

    if action not in {"start", "stop", "restart"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported action: {action}",
        )

    try:
        if service["type"] == "pm2":
            command = [
                "/home/mainsup/.nvm/versions/node/v24.18.1/bin/pm2",
                action,
                service["pm2_name"],
            ]

        elif service["type"] == "systemd":
            command = [
                "sudo",
                "-n",
                "/usr/bin/systemctl",
                action,
                service["unit"],
            ]
        elif service["type"] == "user-systemd":
            command = [
        "systemctl",
        "--user",
        action,
        service["unit"],
         ]

        else:
            raise HTTPException(
                status_code=500,
                detail="Invalid service configuration",
            )

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        return {
            "success": result.returncode == 0,
            "service": service_name,
            "action": action,
            "manager": service["type"],
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
            "return_code": result.returncode,
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=f"{action} operation timed out",
        )


class JournalCollector:
    def collect(self, lines: int = 50) -> Dict[str, Any]:
        try:
            output = subprocess.check_output(
                [
                    "journalctl",
                    "-p", "3",
                    "--since", "10 minutes ago",
                    "-n", str(lines),
                    "--no-pager",
                    "-o", "json",
                ],
                text=True,
            )

            entries = [
                json.loads(line)
                for line in output.strip().split("\n")
                if line
            ]

            return {
                "errors_count": len(entries),
                "entries": entries,
            }

        except Exception as exc:
            print(f"[JournalCollector] {exc}")
            return {
                "errors_count": 0,
                "entries": [],
            }


class DetectionEngine:
    def check_systemd_services(self, services):
        return [{
            "id": f"systemd-{svc['name']}",
            "title": f"Service Failed: {svc['name']}",
            "severity": "critical", "source": "systemd", "timestamp": time.time(),
        } for svc in services if svc.get("status") == "failed"]

    def check_pm2_processes(self, processes):
        return [{
            "id": f"pm2-{proc['name']}",
            "title": f"PM2 Process Issue: {proc['name']}",
            "severity": "warning", "source": "pm2", "timestamp": time.time(),
        } for proc in processes if proc.get("status") in ["errored", "stopped"]]


def check_listening_ports(ports):
    return []


def check_journal_errors(journal):
    """
    Detect unusually high system journal error frequency while ignoring
    known low-value SSH connection-reset noise.
    """
    entries = journal.get("entries", [])

    relevant_errors = []

    for entry in entries:
        message = str(
            entry.get("MESSAGE")
            or entry.get("message")
            or ""
        ).lower()

        # Ignore common internet/SSH scanning noise.
        if "kex_exchange_identification" in message:
            continue

        if "connection reset by peer" in message and (
            "sshd" in message or "sshd-session" in message
        ):
            continue

        relevant_errors.append(entry)

    if len(relevant_errors) > 10:
        return [{
            "id": "journal-high-errors",
            "title": "High system log error frequency detected",
            "severity": "warning",
            "source": "journalctl",
            "timestamp": time.time(),
        }]

    return []


def detect_application_failures(apps):
    return [{
        "id": f"app-{app['name']}",
        "title": f"Application Failure: {app['name']}",
        "severity": "critical", "source": "application", "timestamp": time.time(),
    } for app in apps if app.get("status") == "failed"]


class IncidentManager:
    def __init__(self):
        self.active_incidents = {}
        self.history = []

    def process(self, detections):
        current_ids = {d["id"] for d in detections}
        for inc_id in list(self.active_incidents.keys()):
            if inc_id not in current_ids:
                resolved_inc = self.active_incidents.pop(inc_id)
                resolved_inc["resolved_at"] = time.time()
                self.history.append(resolved_inc)
        for det in detections:
            if det["id"] not in self.active_incidents:
                self.active_incidents[det["id"]] = det
        return list(self.active_incidents.values())

    def get_active(self):
        return list(self.active_incidents.values())

    def get_history(self):
        return self.history


incident_manager = IncidentManager()
email_notifier = EmailNotifier()
latest_agent_data = {}

mia_process_monitor = ProcessBaselineMonitor(
    name="mia-web",
    cwd="/home/mainsup/projects/MIA/mia-web/mia-web-app",
)

# Prevent repeated journal-high-errors emails after Sentinel restarts.
# This state is intentionally kept outside IncidentManager because
# IncidentManager is reset whenever the API process restarts.
journal_error_email_sent = False

def run_agent_loop():
    global latest_agent_data
    detector = DetectionEngine()
    journal_collector = JournalCollector()
    print("[Sentinel Background Agent] Daemon thread started successfully.")
    while True:
        try:
            systemd_svcs = get_systemd_services()
            pm2_svcs = get_pm2_processes()
            ports = get_listening_ports()
            journal = journal_collector.collect()
            apps = collect_applications()
            detections = (
                detector.check_systemd_services(systemd_svcs)
                + detector.check_pm2_processes(pm2_svcs)
                + check_listening_ports(ports)
                + check_journal_errors(journal)
                + detect_application_failures(apps)
            )
            mia_memory = mia_process_monitor.update()
            if mia_memory.get("incident"):
                detections.append(mia_memory["incident"])
            previous_incident_ids = set(incident_manager.active_incidents.keys())
            incident_events = incident_manager.process(detections)

            for incident in incident_events:
                incident_id = incident.get("id")

                # Journal errors are noisy and can survive Sentinel restarts.
                # Send the email only once while the condition remains active.
                if incident_id == "journal-high-errors":
                    global journal_error_email_sent

                    if not journal_error_email_sent:
                        email_notifier.send_incident(incident)
                        journal_error_email_sent = True

           # All other incidents keep the normal "new incident" behavior.
                elif incident_id not in previous_incident_ids:
                    email_notifier.send_incident(incident)

             # Reset the journal email lock once the journal condition clears.
            if not any(
                incident.get("id") == "journal-high-errors"
                for incident in incident_events
            ):
                journal_error_email_sent = False
            latest_agent_data = {
                "active_incidents": incident_manager.get_active(),
                "events": incident_events,
                "history": incident_manager.get_history(),
                "journal": journal,
                "applications": apps,
            }
        except Exception as err:
            print(f"[Sentinel Background Agent Error] {err}")
        time.sleep(COLLECTION_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    agent_thread = threading.Thread(target=run_agent_loop, daemon=True)
    agent_thread.start()
    yield
    print("[Sentinel API] Shutting down.")


app = FastAPI(title="DSE Sentinel API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "dse-sentinel-api"}


@app.get("/api/system")
def system():
    return get_system_info()


@app.get("/api/processes")
def processes():
    return get_top_processes()


@app.get("/api/services")
def services():
    return {"systemd": get_systemd_services(), "pm2": get_pm2_processes()}


@app.get("/api/network")
def network():
    return {"network": get_network_info(), "listening_ports": get_listening_ports()}


@app.post("/api/test-email")
def test_email():
    test_incident = {
        "id": "manual-email-test", "title": "Sentinel Email Test",
        "severity": "critical", "source": "manual", "timestamp": time.time(),
    }
    return {"success": email_notifier.send_incident(test_incident)}


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
        "services": {"systemd": systemd_svcs, "pm2": pm2_svcs},
        "network": {"listening_ports": listening},
        "listening_ports": listening,
        "incidents": {
            "active": latest_agent_data.get("active_incidents", []),
            "events": latest_agent_data.get("events", []),
            "history": latest_agent_data.get("history", []),
        },
        "journal": latest_agent_data.get("journal", {}),
        "process_baselines": {"mia-web": mia_process_monitor.get_status()},
        "controlled_services": list(CONTROLLED_SERVICES.keys()),
    }


@app.post("/api/services/{service_name}/action")
def service_action(service_name: str, action: str = Query(...)):
    return run_controlled_service(service_name, action)


@app.get("/api/services/{service_name}/logs")
def get_service_logs(service_name: str, lines: int = 50):
    clean_name = "".join(c for c in service_name if c.isalnum() or c in "._-")
    try:
        output = subprocess.check_output(
            ["journalctl", "-u", clean_name, "-n", str(lines), "--no-pager"],
            text=True, stderr=subprocess.STDOUT,
        )
        return {"service": clean_name, "logs": [line for line in output.strip().split("\n") if line]}
    except Exception as exc:
        return {"service": clean_name, "error": str(exc), "logs": []}


@app.get("/api/services/{service_name}/stats")
def get_service_stats(service_name: str):
    clean_name = "".join(c for c in service_name if c.isalnum() or c in "._-")
    try:
        output = subprocess.check_output(
            ["systemctl", "show", clean_name, "--property=NRestarts,ActiveState,SubState,MainPID,ExecMainStatus"],
            text=True,
        )
        props = dict(line.split("=", 1) for line in output.strip().split("\n") if "=" in line)
        return {
            "service": clean_name,
            "restarts_crashes": int(props.get("NRestarts", 0)),
            "active_state": props.get("ActiveState", "unknown"),
            "sub_state": props.get("SubState", "unknown"),
            "main_pid": props.get("MainPID", "0"),
        }
    except Exception as exc:
        return {"service": clean_name, "error": str(exc), "restarts_crashes": 0}


@app.post("/api/mobile/{app_name}/build")
def mobile_build(app_name: str, deploy: bool = False):
    if app_name not in MOBILE_APPS:
        raise HTTPException(
            status_code=404,
            detail="Unknown mobile app",
        )

    with mobile_jobs_lock:
        running_jobs = [
            job
            for job in mobile_jobs.values()
            if job["app"] == app_name
            and job["status"] in {"queued", "running"}
        ]

        if running_jobs:
            return {
                "success": False,
                "status": "already_running",
                "job_id": running_jobs[0]["id"],
                "message": (
                    f"{app_name} already has a build running."
                ),
            }

        job_id = (
            f"{app_name.lower().replace(' ', '-')}"
            f"-{int(time.time())}"
        )

        mobile_jobs[job_id] = {
            "id": job_id,
            "app": app_name,
            "deploy": deploy,
            "mode": (
                "production-submit"
                if deploy
                else "production-build"
            ),
            "status": "queued",
            "created_at": time.time(),
        }

    thread = threading.Thread(
        target=run_mobile_job,
        args=(job_id, app_name, deploy),
        daemon=True,
    )

    thread.start()

    return {
        "success": True,
        "job_id": job_id,
        "app": app_name,
        "deploy": deploy,
        "status": "queued",
    }


@app.get("/api/mobile/jobs/{job_id}")
def mobile_job(job_id: str):
    with mobile_jobs_lock:
        job = mobile_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/controlled-services")
def controlled_services():
    services = []

    for name, config in CONTROLLED_SERVICES.items():
        services.append({
            "name": name,
            "type": config["type"],
            "unit": config.get("unit"),
            "pm2_name": config.get("pm2_name"),
        })

    return {
        "services": services
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
