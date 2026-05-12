import subprocess
import json
import glob
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from deps import verify_token, OBSIDIAN_VAULT, SECRET_TOKEN

router = APIRouter(tags=["actions"])

# Whitelisted services that can be managed
MANAGED_SERVICES = {
    "discipline": {"type": "launchctl", "plist": "ai.hermes.discipline", "port": 8899},
    "hermes-gateway": {"type": "launchctl", "plist": "ai.hermes.gateway", "port": None},
}


@router.post("/api/actions/restart-service")
def action_restart_service(request: Request, body: dict = None):
    """Restart a managed service. Body: {"service": "discipline"}"""
    verify_token(request)
    body = body or {}
    service = body.get("service", "")
    if service not in MANAGED_SERVICES:
        return JSONResponse({"error": f"Unknown service: {service}"}, status_code=400)

    svc = MANAGED_SERVICES[service]
    if svc["type"] == "launchctl":
        uid = os.getuid()
        try:
            result = subprocess.run(
                ["launchctl", "kickstart", "-k", f"gui/{uid}/{svc['plist']}"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                return {"ok": True, "message": f"{service} restarted"}
            else:
                return JSONResponse({"error": result.stderr.strip()}, status_code=500)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"error": "Unsupported service type"}, status_code=400)


@router.post("/api/actions/create-note")
def action_create_note(request: Request, body: dict = None):
    """Create an Obsidian note. Body: {"path": "Notes/filename.md", "content": "..."}"""
    verify_token(request)
    body = body or {}
    rel_path = body.get("path", "").strip("/")
    content = body.get("content", "")

    if not rel_path:
        return JSONResponse({"error": "path is required"}, status_code=400)

    vault = os.environ.get("OBSIDIAN_VAULT", os.path.expanduser("~/Documents/Obsidian Vault"))
    full_path = os.path.normpath(os.path.join(vault, rel_path))

    # Security: ensure path stays within vault
    if not full_path.startswith(os.path.normpath(vault)):
        return JSONResponse({"error": "Path outside vault"}, status_code=403)

    if os.path.exists(full_path):
        return JSONResponse({"error": "File already exists"}, status_code=409)

    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)
        return {"ok": True, "message": f"Created {rel_path}"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/actions/cron-list")
def action_cron_list(request: Request):
    """List available cron jobs for manual trigger."""
    verify_token(request)
    try:
        result = subprocess.run(
            ["python3", os.path.expanduser("~/.hermes/scripts/cron_helper.py"), "list"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return JSONResponse({"error": result.stderr.strip()}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/actions/cron-jobs")
def action_cron_jobs(request: Request):
    """List cron jobs from Hermes jobs.json (read-only)."""
    verify_token(request)
    jobs_path = os.path.expanduser("~/.hermes/cron/jobs.json")
    if not os.path.exists(jobs_path):
        return []
    try:
        with open(jobs_path) as f:
            data = json.load(f)
        jobs = data.get("jobs", [])
        return [{
            "id": j.get("id"),
            "name": j.get("name"),
            "schedule": j.get("schedule_display", ""),
            "enabled": j.get("enabled", False),
            "last_status": j.get("last_status"),
            "last_run": j.get("last_run_at"),
            "next_run": j.get("next_run_at"),
        } for j in jobs if j.get("enabled")]
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/actions/trigger-cron")
def action_trigger_cron(request: Request, body: dict = None):
    """Trigger a cron job by ID."""
    verify_token(request)
    body = body or {}
    job_id = body.get("job_id", "")
    if not job_id:
        return JSONResponse({"error": "job_id required"}, status_code=400)
    try:
        result = subprocess.run(
            ["hermes", "cron", "run", job_id],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return {"ok": True, "message": f"Job {job_id} triggered"}
        return JSONResponse({"error": result.stderr.strip() or "trigger failed"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/usage")
def api_usage():
    """Return AI usage data from calibration files."""
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    usage_dir = os.path.join(hermes_home, "usage")
    result = {}
    for f in glob.glob(os.path.join(usage_dir, "*calibration*.json")):
        name = os.path.basename(f).replace(".json", "")
        try:
            with open(f) as fp:
                result[name] = json.load(fp)
        except:
            pass
    return result
