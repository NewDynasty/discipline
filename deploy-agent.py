#!/usr/bin/env python3
"""
Deploy Agent — 轻量部署 API，独立于 Discipline 主服务运行
端口: 8900, 只监听 127.0.0.1
认证: Bearer token (通过环境变量 DEPLOY_TOKEN 配置)
"""

import os
import json
import subprocess
import asyncio
import threading
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# --- Config ---
WORK_DIR = Path(os.environ.get("DEPLOY_WORKDIR", "/opt/discipline-git"))
DEPLOY_TOKEN = os.environ.get("DEPLOY_TOKEN", "")
PORT = int(os.environ.get("DEPLOY_PORT", "8900"))
ROLLBACK_TAG = "discipline-rollback:latest"

app = FastAPI(title="Deploy Agent", version="1.0")

# --- Deploy state ---
deploy_lock = threading.Lock()
deploy_status = {"deploying": False, "last_result": None, "started_at": None}

# --- Auth ---
def verify_token(authorization: str = Header(default="")):
    if not DEPLOY_TOKEN:
        return  # no token configured = no auth
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    if token != DEPLOY_TOKEN:
        raise HTTPException(401, "Unauthorized")


# --- Helpers ---
def run_cmd(cmd: str, cwd: str = None, timeout: int = 120) -> tuple[bool, str]:
    """Run shell command, return (success, output)"""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=cwd or WORK_DIR, timeout=timeout
        )
        output = r.stdout.strip() + ("\n" + r.stderr.strip() if r.stderr.strip() else "")
        return r.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except Exception as e:
        return False, str(e)


def get_current_commit() -> dict:
    ok, hash_out = run_cmd("git rev-parse --short HEAD")
    ok2, msg_out = run_cmd("git log --oneline -1 --format='%s'")
    ok3, time_out = run_cmd("git log -1 --format='%ci'")
    ok4, hash_full = run_cmd("git rev-parse HEAD")
    return {
        "hash": hash_out.strip("'") if ok else "unknown",
        "hash_full": hash_full.strip("'") if ok4 else "",
        "message": msg_out.strip("'") if ok2 else "",
        "time": time_out.strip("'") if ok3 else "",
    }


def get_container_status() -> dict:
    ok, out = run_cmd("docker inspect discipline --format '{{.State.Status}}' 2>/dev/null")
    status = out.strip().strip("'") if ok else "not found"
    ok2, out2 = run_cmd("docker inspect discipline --format '{{.Created}}' 2>/dev/null")
    created = out2.strip().strip("'") if ok2 else ""
    return {"status": status, "created": created, "running": status == "running"}


def get_resource_usage() -> dict:
    # Disk
    ok, out = run_cmd("df -h / --output=pcent,size | tail -1")
    parts = out.strip().split() if ok else ["0%", "0"]
    disk_pct = parts[0] if len(parts) > 0 else "0%"
    disk_total = parts[1] if len(parts) > 1 else "0"

    # Memory
    ok2, out2 = run_cmd("free -m | grep Mem")
    if ok2 and out2:
        m = out2.split()
        mem_total = int(m[1]) if len(m) > 1 else 0
        mem_used = int(m[2]) if len(m) > 2 else 0
        mem_pct = f"{mem_used}/{mem_total}MB ({mem_used*100//mem_total if mem_total else 0}%)"
    else:
        mem_pct = "unknown"

    return {"disk": f"{disk_pct} of {disk_total}", "memory": mem_pct}


# --- API: Status ---
@app.get("/api/deploy/status")
def status(auth=Depends(verify_token)):
    commit = get_current_commit()
    container = get_container_status()
    resource = get_resource_usage()
    return {
        "commit": commit,
        "container": container,
        "resource": resource,
        "deploying": deploy_status["deploying"],
        "last_result": deploy_status["last_result"],
    }


# --- API: Commit History ---
class CommitsQuery(BaseModel):
    count: int = 10

@app.get("/api/deploy/commits")
def commits(count: int = 10, auth=Depends(verify_token)):
    ok, out = run_cmd(f"git log --oneline -{min(count, 30)} --format='%H|%h|%s|%ci'")
    if not ok:
        raise HTTPException(500, out)

    result = []
    for line in out.strip().split("\n"):
        if not line.strip() or "|" not in line:
            continue
        parts = line.strip("'").split("|")
        if len(parts) >= 4:
            result.append({
                "hash_full": parts[0],
                "hash": parts[1],
                "message": parts[2],
                "time": parts[3],
            })
    return result


# --- API: Deploy (SSE streaming) ---
class DeployRequest(BaseModel):
    ref: str = "latest"  # "latest" or commit hash

@app.post("/api/deploy/run")
def run_deploy(req: DeployRequest, auth=Depends(verify_token)):
    if deploy_status["deploying"]:
        raise HTTPException(409, "Deployment already in progress")

    return StreamingResponse(
        _deploy_stream(req.ref),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _deploy_stream(ref: str):
    """Generator that yields SSE events during deployment"""
    import queue
    q = queue.Queue()

    def worker():
        if not deploy_lock.acquire(blocking=False):
            q.put(("error", "Cannot acquire deploy lock"))
            return

        deploy_status["deploying"] = True
        deploy_status["started_at"] = datetime.now().isoformat()
        steps = [
            ("💾 保存回滚镜像", _step_save_rollback),
            ("📦 拉取代码", lambda: _step_fetch(ref)),
            ("🔨 构建镜像", _step_build),
            ("🏥 健康检查", _step_health_check),
        ]

        result = {"success": False, "steps": [], "commit": None}

        for label, step_fn in steps:
            q.put(("step", label))
            ok, detail = step_fn()
            q.put(("result", {"label": label, "ok": ok, "detail": detail}))
            result["steps"].append({"label": label, "ok": ok, "detail": detail})
            if not ok:
                q.put(("error", f"❌ {label} 失败: {detail}"))
                result["success"] = False
                break
        else:
            result["success"] = True
            result["commit"] = get_current_commit()
            q.put(("done", f"✅ 部署完成 — {result['commit']['hash']} {result['commit']['message']}"))

        deploy_status["deploying"] = False
        deploy_status["last_result"] = result
        deploy_lock.release()

    # Start deploy in background thread
    t = threading.Thread(target=worker, daemon=True)
    t.start()

    # Yield SSE events
    while t.is_alive() or not q.empty():
        try:
            event_type, data = q.get(timeout=1)
            yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except queue.Empty:
            continue

    # Final flush
    try:
        while True:
            event_type, data = q.get_nowait()
            yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    except queue.Empty:
        pass


# --- Deploy Steps ---
def _step_save_rollback() -> tuple[bool, str]:
    ok, img = run_cmd("docker compose images -q discipline 2>/dev/null | head -1")
    if ok and img.strip():
        ok2, _ = run_cmd(f"docker tag {img.strip()} {ROLLBACK_TAG}")
        return ok2, f"已保存 {img.strip()[:12]} → {ROLLBACK_TAG}"
    return True, "无当前镜像，跳过回滚备份"


def _step_fetch(ref: str) -> tuple[bool, str]:
    ok, out = run_cmd("git fetch origin main")
    if not ok:
        return False, f"git fetch 失败: {out}"

    if ref == "latest":
        ok2, out2 = run_cmd("git reset --hard origin/main")
    else:
        ok2, out2 = run_cmd(f"git reset --hard {ref}")

    if not ok2:
        return False, f"git reset 失败: {out2}"

    ok3, log = run_cmd("git log --oneline -1")
    return ok3, log or out2


def _step_build() -> tuple[bool, str]:
    ok, out = run_cmd("docker compose up -d --build", timeout=180)
    return ok, out[-500:] if len(out) > 500 else out


def _step_health_check() -> tuple[bool, str]:
    import time
    for i in range(6):
        time.sleep(2)
        ok, out = run_cmd("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8899/portal")
        if ok and out.strip("'") == "200":
            return True, f"HTTP 200 (attempt {i+1})"
    ok, out = run_cmd("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8899/portal")
    code = out.strip("'") if ok else "error"
    return False, f"HTTP {code} — 服务异常"


# --- Rollback ---
@app.post("/api/deploy/rollback")
def rollback(auth=Depends(verify_token)):
    if deploy_status["deploying"]:
        raise HTTPException(409, "Deployment in progress")

    ok, out = run_cmd(f"docker images {ROLLBACK_TAG} -q")
    if not ok or not out.strip():
        raise HTTPException(404, "No rollback image found")

    # Stop current, tag rollback as current image name, start
    ok2, out2 = run_cmd(
        f"docker compose down && "
        f"docker tag {ROLLBACK_TAG} discipline-git-discipline:latest && "
        f"docker compose up -d"
    )
    if not ok2:
        return {"success": False, "error": out2}

    import time; time.sleep(3)
    container = get_container_status()
    return {"success": container["running"], "container": container}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT)
