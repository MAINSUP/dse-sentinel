import subprocess
from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/service-controls", tags=["service-controls"])

SERVICE_MAP: Dict[str, Dict[str, Any]] = {
    "mia-api": {"label": "MIA API", "kind": "systemd", "unit": "mia-api.service", "actions": ["start", "stop", "restart"]},
    "seavie-api": {"label": "SeaVie API", "kind": "systemd", "unit": "seavie-api.service", "actions": ["start", "stop", "restart"]},
    "mia-web": {"label": "MIA Web", "kind": "pm2", "process": "mia-web", "actions": ["start", "stop", "restart"]},
    "mia-mobile": {"label": "MIA Mobile", "kind": "eas", "directory": "/home/mainsup/projects/MIA/mobile", "actions": ["build"]},
}

PM2 = "/home/mainsup/.nvm/versions/node/v24.18.1/bin/pm2"
EAS = "/home/mainsup/.nvm/versions/node/v24.18.1/bin/npx"

class ServiceAction(BaseModel):
    service: str
    action: str

def run(command: list[str], cwd: str | None = None):
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=30, check=False)

@router.get("")
def list_controlled_services():
    return {key: {"id": key, "label": value["label"], "kind": value["kind"], "actions": value["actions"]} for key, value in SERVICE_MAP.items()}

@router.post("")
def control_service(request: ServiceAction):
    target = SERVICE_MAP.get(request.service)
    if not target:
        raise HTTPException(status_code=404, detail="Unknown service")
    if request.action not in target["actions"]:
        raise HTTPException(status_code=400, detail="Action is not allowed for this service")

    if target["kind"] == "systemd":
        result = run(["systemctl", request.action, target["unit"]])
    elif target["kind"] == "pm2":
        result = run([PM2, request.action, target["process"]])
    else:
        result = run([EAS, "eas-cli", "build", "--platform", "all", "--profile", "production", "--non-interactive", "--no-wait"], cwd=target["directory"])

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=(result.stderr or result.stdout or "Command failed")[-2000:])

    return {"success": True, "service": request.service, "label": target["label"], "action": request.action, "output": (result.stdout or "")[-2000:]}
