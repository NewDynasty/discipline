"""
Portal routes — service status, research notes, kanban boards, earlyrise summary,
and static page serving. All driven by portal-registry.yaml.
"""

import glob
import os
import re
import socket
import sqlite3

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

# --- Shared helpers ---
from deps import OBSIDIAN_VAULT, PORTAL_DIR, db_conn, get_db, _calc_streak, VAULT_REGISTRY, PORTAL_REGISTRY

router = APIRouter(tags=["portal"])

# ── Service health (from registry) ───────────────────────────────────────────

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
        if not prev or not prev.get("online"):
            entry["uptime_since"] = now
        else:
            entry["uptime_since"] = prev.get("uptime_since", now)
        entry["last_up"] = now
    else:
        if prev and prev.get("online"):
            entry["uptime_since"] = None
        else:
            entry["uptime_since"] = None
        entry["last_up"] = prev.get("last_up") if prev else None

    _health_cache[port] = entry
    return entry


@router.get("/api/portal/status")
def portal_status():
    """Service health check — reads services from portal-registry.yaml."""
    services = PORTAL_REGISTRY.get("services", [])
    results = []
    for svc in services:
        h = _get_health(svc)
        uptime_secs = None
        if h["online"] and h.get("uptime_since"):
            import time as _time
            uptime_secs = int(_time.time() - h["uptime_since"])

        results.append({
            "name": svc["name"],
            "port": svc["port"],
            "category": svc.get("category", ""),
            "online": h["online"],
            "latency_ms": h["latency"],
            "last_check": round(h["last_check"]),
            "last_up": round(h["last_up"]) if h.get("last_up") else None,
            "uptime_secs": uptime_secs,
        })
    return results


# ── Navigation API ────────────────────────────────────────────────────────────

@router.get("/api/portal/nav")
def portal_nav():
    """Return navigation items from portal-registry.yaml for frontend."""
    systems = PORTAL_REGISTRY.get("systems", [])
    nav_items = []
    for sys in systems:
        if not sys.get("nav", False):
            continue
        nav_items.append({
            "id": sys.get("id", ""),
            "name": sys.get("name", ""),
            "href": sys.get("path", ""),
            "icon": sys.get("icon", ""),
            "brand": sys.get("brand", False),
        })
    return {"nav": nav_items}


# ── Systems overview ──────────────────────────────────────────────────────────

@router.get("/api/portal/systems")
def portal_systems():
    """Return all registered systems with metadata."""
    systems = PORTAL_REGISTRY.get("systems", [])
    result = []
    for sys in systems:
        entry = {
            "id": sys.get("id", ""),
            "name": sys.get("name", ""),
            "path": sys.get("path", ""),
            "icon": sys.get("icon", ""),
            "nav": sys.get("nav", False),
            "brand": sys.get("brand", False),
            "auth_level": sys.get("auth_level", ""),
            "category": sys.get("category", ""),
        }
        # Check if HTML file exists
        html_file = sys.get("html", "")
        if html_file:
            entry["has_page"] = os.path.exists(os.path.join(PORTAL_DIR, html_file))
        # Check proxy availability
        proxy = sys.get("proxy", "")
        if proxy:
            entry["has_proxy"] = True
        result.append(entry)
    return result


# ── Research notes ────────────────────────────────────────────────────────────

@router.get("/api/portal/research")
def portal_research():
    """List recent research notes from Obsidian vault."""
    research_dir_name = VAULT_REGISTRY.get("portal", {}).get("research_dir", "Research")
    research_dir = os.path.join(OBSIDIAN_VAULT, research_dir_name)
    if not os.path.isdir(research_dir):
        return []

    notes = []
    for f in glob.glob(os.path.join(research_dir, "**/*.md"), recursive=True):
        title = os.path.splitext(os.path.basename(f))[0]
        tags = []
        mtime = os.path.getmtime(f)
        try:
            with open(f, "r", encoding="utf-8") as fh:
                head = fh.read(500)
                fm = re.search(r'^---\s*\n(.*?)\n---', head, re.DOTALL)
                if fm:
                    tag_match = re.search(r'tags:\s*\[(.*?)\]', fm.group(1))
                    if tag_match:
                        tags = [t.strip().strip('"\'') for t in tag_match.group(1).split(",") if t.strip()]
        except Exception:
            pass
        rel = os.path.relpath(f, OBSIDIAN_VAULT)
        notes.append({"title": title, "tags": tags, "mtime": mtime,
                       "url": f"/docs/{rel}"})

    notes.sort(key=lambda x: x["mtime"], reverse=True)
    for n in notes:
        del n["mtime"]
    return notes[:10]

# ── Kanban boards ─────────────────────────────────────────────────────────────

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

# ── Early Rise summary ────────────────────────────────────────────────────────

@router.get("/api/portal/earlyrise")
def portal_earlyrise():
    """Early Rise summary for portal."""
    streak = _calc_streak()
    with db_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as total, SUM(pass) as passed FROM checkins").fetchone()
    total = row["total"] if row else 0
    passed = row["passed"] if row and row["passed"] else 0
    return {"streak": streak, "total": total, "passed": passed}

# ── Serve Portal Frontend pages (from registry) ──────────────────────────────

def _register_page_routes():
    """Register page routes from portal-registry.yaml."""
    systems = PORTAL_REGISTRY.get("systems", [])
    for sys_cfg in systems:
        html_file = sys_cfg.get("html", "")
        path = sys_cfg.get("path", "")
        if not html_file or not path:
            continue
        # Skip docs (has its own SPA routing with /docs/{path})
        if sys_cfg.get("id") == "docs":
            continue

        html_path = os.path.join(PORTAL_DIR, html_file)
        route_name = f"serve_{sys_cfg['id']}"

        def _make_handler(fp):
            def handler():
                if os.path.exists(fp):
                    return FileResponse(fp, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
                return JSONResponse({"error": "Page not found"}, status_code=404)
            return handler

        handler = _make_handler(html_path)
        handler.__name__ = route_name

        # Register with and without trailing slash
        router.get(path)(handler)
        if not path.endswith("/"):
            router.get(path + "/")(handler)

_register_page_routes()
