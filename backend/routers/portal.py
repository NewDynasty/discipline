"""
Portal routes — service status, research notes, kanban boards, earlyrise summary,
and static page serving (/portal, /models, /deploy).
"""

import glob
import os
import re
import socket
import sqlite3

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

# --- Shared helpers ---
from deps import OBSIDIAN_VAULT, PORTAL_DIR, db_conn, get_db, _calc_streak, VAULT_REGISTRY

router = APIRouter(tags=["portal"])

# ── Service health ──────────────────────────────────────────────────────────

def _check_port(host: str, port: int, timeout: float = 1.0):
    """TCP connect check. Returns (online: bool, latency_ms: float|None)."""
    try:
        import time
        t0 = time.monotonic()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
        latency = round((time.monotonic() - t0) * 1000, 1)
        return True, latency
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False, None

SERVICES = [
    {"name": "Hermes Gateway", "port": 8000},
    {"name": "Early Rise", "port": 8899},
    {"name": "Codex Server", "port": 8090},
    {"name": "Obsidian Kanban", "port": 27124},
    {"name": "Sync-Hub", "port": 8081},
    {"name": "RSSHub", "port": 1200},
]

# In-memory health history: {port: {online, latency, last_check, last_up, uptime_since}}
_health_cache: dict = {}

def _get_health(svc: dict) -> dict:
    """Check service and update health cache. Returns enriched status."""
    import time as _time
    port = svc["port"]
    online, latency = _check_port("127.0.0.1", port)
    now = _time.time()
    prev = _health_cache.get(port)

    entry = {"online": online, "latency": latency, "last_check": now}

    if online:
        # Track when service first came online (uptime_since)
        if not prev or not prev.get("online"):
            entry["uptime_since"] = now  # just came online
        else:
            entry["uptime_since"] = prev.get("uptime_since", now)
        entry["last_up"] = now
    else:
        if prev and prev.get("online"):
            entry["uptime_since"] = None  # just went offline
        else:
            entry["uptime_since"] = None
        entry["last_up"] = prev.get("last_up") if prev else None

    _health_cache[port] = entry
    return entry


@router.get("/api/portal/status")
def portal_status():
    """Service health check with latency, last check time, and uptime."""
    results = []
    for svc in SERVICES:
        h = _get_health(svc)
        uptime_secs = None
        if h["online"] and h.get("uptime_since"):
            import time as _time
            uptime_secs = int(_time.time() - h["uptime_since"])

        results.append({
            "name": svc["name"],
            "port": svc["port"],
            "online": h["online"],
            "latency_ms": h["latency"],
            "last_check": round(h["last_check"]),
            "last_up": round(h["last_up"]) if h.get("last_up") else None,
            "uptime_secs": uptime_secs,
        })
    return results

# ── Research notes ──────────────────────────────────────────────────────────

@router.get("/api/portal/research")
def portal_research():
    """List recent research notes from Obsidian vault."""
    research_dir_name = VAULT_REGISTRY.get("portal", {}).get("research_dir", "Research")
    research_dir = os.path.join(OBSIDIAN_VAULT, research_dir_name)
    if not os.path.isdir(research_dir):
        return []

    notes = []
    for f in glob.glob(os.path.join(research_dir, "*.md")):
        title = os.path.splitext(os.path.basename(f))[0]
        # Parse frontmatter for tags
        tags = []
        mtime = os.path.getmtime(f)
        try:
            with open(f, "r", encoding="utf-8") as fh:
                head = fh.read(500)
                # Extract tags from frontmatter
                fm = re.search(r'^---\s*\n(.*?)\n---', head, re.DOTALL)
                if fm:
                    tag_match = re.search(r'tags:\s*\[(.*?)\]', fm.group(1))
                    if tag_match:
                        tags = [t.strip().strip('"\'') for t in tag_match.group(1).split(",") if t.strip()]
        except Exception:
            pass
        notes.append({"title": title, "tags": tags, "mtime": mtime,
                       "url": f"/docs/{research_dir_name}/{os.path.basename(f)}"})

    # Sort by mtime desc, take 10
    notes.sort(key=lambda x: x["mtime"], reverse=True)
    for n in notes:
        del n["mtime"]
    return notes[:10]

# ── Kanban boards ───────────────────────────────────────────────────────────

@router.get("/api/portal/kanban")
def portal_kanban():
    """List kanban boards from Obsidian vault."""
    kanban_dir_name = VAULT_REGISTRY.get("portal", {}).get("kanban_dir", "Kanban")
    kanban_dir = os.path.join(OBSIDIAN_VAULT, kanban_dir_name)
    if not os.path.isdir(kanban_dir):
        return []

    boards = []
    for f in glob.glob(os.path.join(kanban_dir, "*.md")):
        name = os.path.splitext(os.path.basename(f))[0]
        # Count tasks (lines starting with - [ ] or - [x])
        count = 0
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    if re.match(r'^\s*- \[[ x]\]', line):
                        count += 1
        except Exception:
            pass
        boards.append({"name": name, "count": f"{count} 任务" if count else "空",
                        "url": f"/docs/{kanban_dir_name}/{os.path.basename(f)}"})
    return boards

# ── Early Rise summary ──────────────────────────────────────────────────────

@router.get("/api/portal/earlyrise")
def portal_earlyrise():
    """Early Rise summary for portal."""
    streak = _calc_streak()
    with db_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as total, SUM(pass) as passed FROM checkins").fetchone()
    total = row["total"] if row else 0
    passed = row["passed"] if row and row["passed"] else 0
    return {"streak": streak, "total": total, "passed": passed}

# ── Serve Portal Frontend pages ─────────────────────────────────────────────

@router.get("/portal")
@router.get("/portal/")
def serve_portal():
    html_path = os.path.join(PORTAL_DIR, "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return JSONResponse({"error": "Portal not found"}, status_code=404)


@router.get("/models")
@router.get("/models/")
def serve_models():
    html_path = os.path.join(PORTAL_DIR, "models.html")
    if os.path.exists(html_path):
        return FileResponse(html_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return JSONResponse({"error": "Models page not found"}, status_code=404)


@router.get("/deploy")
@router.get("/deploy/")
def serve_deploy():
    html_path = os.path.join(PORTAL_DIR, "deploy.html")
    if os.path.exists(html_path):
        return FileResponse(html_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    return JSONResponse({"error": "Deploy page not found"}, status_code=404)
