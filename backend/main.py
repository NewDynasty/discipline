"""
Early Rise API - FastAPI + SQLite
Single-user early-rise tracking with token auth.
"""
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import socket
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# --- Config ---
DB_PATH = os.environ.get("EARLY_RISE_DB", "data/earlyrise.db")
SECRET_TOKEN = os.environ.get("EARLY_RISE_TOKEN", "earlyrise2026")
STATIC_DIR = os.environ.get("EARLY_RISE_STATIC", os.path.join(os.path.dirname(__file__), "..", "frontend"))
TOKEN_EXPIRE_HOURS = int(os.environ.get("TOKEN_EXPIRE_HOURS", "168"))

# --- Database ---
def get_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS checkins (
            date TEXT PRIMARY KEY,
            wake_time TEXT NOT NULL,
            pass INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

@contextmanager
def db_conn():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

# --- Auth ---
def verify_token(request: Request) -> bool:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    else:
        token = request.cookies.get("token", "")
    
    if not token:
        raise HTTPException(401, "未登录")
    
    with db_conn() as conn:
        row = conn.execute(
            "SELECT expires_at FROM tokens WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            raise HTTPException(401, "无效 token")
        expires = datetime.fromisoformat(row["expires_at"])
        if datetime.utcnow() > expires:
            conn.execute("DELETE FROM tokens WHERE token = ?", (token,))
            raise HTTPException(401, "token 已过期")
    
    return True

# --- Models ---
class LoginRequest(BaseModel):
    password: str

class CheckinRequest(BaseModel):
    wake_time: str  # HH:MM

class CheckinResponse(BaseModel):
    date: str
    wake_time: str
    pass_: bool
    streak: int

class StatsResponse(BaseModel):
    streak: int
    total: int
    pass_count: int
    fail_count: int
    avg_time: Optional[str]
    best_time: Optional[str]
    rate: float

# --- App ---
app = FastAPI(title="Early Rise API", version="1.0.0", docs_url=None, redoc_url=None)

@app.on_event("startup")
def startup():
    init_db()

# --- Projects API (from Obsidian progress.md frontmatter) ---
OBSIDIAN_VAULT = os.environ.get("OBSIDIAN_VAULT", os.path.expanduser("~/Documents/Obsidian Vault"))

def _parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from markdown content."""
    if not content.startswith("---"):
        return {}
    match = __import__("re").match(r"^---\n(.*?)\n---", content, __import__("re").DOTALL)
    if not match:
        return {}
    meta = {}
    for line in match.group(1).split("\n"):
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip() for v in val[1:-1].split(",") if v.strip()]
        elif val.isdigit():
            val = int(val)
        meta[key] = val
    return meta

def _get_one_liner(body: str) -> str:
    """Extract first non-heading, non-quote line as description."""
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("##") or line.startswith(">") or line.startswith("#") or not line:
            continue
        return line
    return ""

@app.get("/api/projects")
def list_projects():
    """List all projects from Obsidian Notes/*-progress.md files."""
    import glob as _glob
    notes_dir = os.path.join(OBSIDIAN_VAULT, "Notes")
    projects = []
    for fpath in sorted(_glob.glob(os.path.join(notes_dir, "*-progress.md"))):
        try:
            with open(fpath) as f:
                content = f.read()
            meta = _parse_frontmatter(content)
            if not meta:
                continue
            # Extract body after frontmatter
            body = __import__("re").sub(r"^---\n.*?\n---\n*", "", content, flags=__import__("re").DOTALL)
            meta["description"] = _get_one_liner(body)
            meta["source_file"] = os.path.basename(fpath)
            # Build clickable URL: prefer port (localhost), then GitHub
            if meta.get("port"):
                meta["url"] = f"/" if meta["port"] == 8899 else "#"
            elif meta.get("github"):
                meta["url"] = f"https://github.com/{meta['github']}"
            projects.append(meta)
        except Exception:
            continue
    # Sort: active first, then by priority, then by completion desc
    priority_map = {"high": 0, "medium": 1, "low": 2}
    projects.sort(key=lambda p: (
        0 if p.get("status") == "active" else 1,
        priority_map.get(p.get("priority", "medium"), 1),
        -(p.get("completion") or 0),
    ))
    return {"projects": projects, "count": len(projects)}

# --- Auth API ---
@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response):
    if req.password != SECRET_TOKEN:
        raise HTTPException(401, "密码错误")
    
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO tokens (token, expires_at) VALUES (?, ?)",
            (token, expires.isoformat()),
        )
    
    resp = JSONResponse({"ok": True, "token": token})
    resp.set_cookie(
        "token", token,
        max_age=TOKEN_EXPIRE_HOURS * 3600,
        httponly=True,
        samesite="lax",
    )
    return resp

@app.post("/api/auth/logout")
def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("token", "")
    if token:
        with db_conn() as conn:
            conn.execute("DELETE FROM tokens WHERE token = ?", (token,))
    return {"ok": True}

# --- Checkin API ---
@app.post("/api/checkin", response_model=CheckinResponse)
def create_checkin(req: CheckinRequest, _=Depends(verify_token)):
    try:
        parts = req.wake_time.split(":")
        h, m = int(parts[0]), int(parts[1])
        assert 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        raise HTTPException(400, "时间格式错误，需要 HH:MM")
    
    target_minutes = 7 * 60  # 07:00
    wake_minutes = h * 60 + m
    passed = wake_minutes <= target_minutes
    
    today = date.today().isoformat()
    
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO checkins (date, wake_time, pass, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(date) DO UPDATE SET
                 wake_time=excluded.wake_time,
                 pass=excluded.pass,
                 updated_at=datetime('now')
            """,
            (today, req.wake_time, int(passed)),
        )
    
    streak = _calc_streak()
    
    return CheckinResponse(
        date=today,
        wake_time=req.wake_time,
        pass_=passed,
        streak=streak,
    )

@app.get("/api/checkin/today")
def get_today(_=Depends(verify_token)):
    today = date.today().isoformat()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT date, wake_time, pass FROM checkins WHERE date = ?", (today,)
        ).fetchone()
    if row:
        return {"date": row["date"], "wake_time": row["wake_time"], "pass": bool(row["pass"])}
    return {"date": today, "wake_time": None, "pass": None}

# --- Stats API ---
@app.get("/api/stats", response_model=StatsResponse)
def get_stats(_=Depends(verify_token)):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT wake_time, pass FROM checkins ORDER BY date"
        ).fetchall()
    
    if not rows:
        return StatsResponse(streak=0, total=0, pass_count=0, fail_count=0,
                             avg_time=None, best_time=None, rate=0.0)
    
    total = len(rows)
    pass_count = sum(1 for r in rows if r["pass"])
    
    times = []
    for r in rows:
        h, m = r["wake_time"].split(":")
        times.append(int(h) * 60 + int(m))
    
    avg_min = sum(times) / len(times)
    best_min = min(times)
    
    def fmt(minutes):
        return f"{int(minutes // 60):02d}:{int(minutes % 60):02d}"
    
    return StatsResponse(
        streak=_calc_streak(),
        total=total,
        pass_count=pass_count,
        fail_count=total - pass_count,
        avg_time=fmt(avg_min),
        best_time=fmt(best_min),
        rate=round(pass_count / total * 100, 1),
    )

@app.get("/api/records")
def get_records(days: int = 30, _=Depends(verify_token)):
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT date, wake_time, pass FROM checkins
               ORDER BY date DESC LIMIT ?""",
            (days,),
        ).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/heatmap")
def get_heatmap(_=Depends(verify_token)):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT date, wake_time, pass FROM checkins ORDER BY date"
        ).fetchall()
    return [dict(r) for r in rows]

# --- Streak calc ---
def _calc_streak() -> int:
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT date, pass FROM checkins
               WHERE pass = 1 ORDER BY date DESC"""
        ).fetchall()
    
    if not rows:
        return 0
    
    today = date.today()
    yesterday = today - timedelta(days=1)
    
    first_date = date.fromisoformat(rows[0]["date"])
    if first_date not in (today, yesterday):
        return 0
    
    streak = 0
    expected = today
    
    for row in rows:
        d = date.fromisoformat(row["date"])
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif d < expected:
            break
    
    return streak

# --- Serve Frontend ---
@app.get("/")
def serve_index():
    html_path = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(html_path)


# --- Command Center Portal API ---

import glob
import re

def _check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """TCP connect check for service health."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

SERVICES = [
    {"name": "Hermes Gateway", "port": 8000},
    {"name": "Early Rise", "port": 8899},
    {"name": "Codex Server", "port": 8090},
    {"name": "Obsidian Kanban", "port": 27124},
    {"name": "Sync-Hub", "port": 8081},
    {"name": "RSSHub", "port": 1200},
]

@app.get("/api/portal/status")
def portal_status():
    """Service health check via TCP connect."""
    results = []
    for svc in SERVICES:
        online = _check_port("127.0.0.1", svc["port"])
        results.append({
            "name": svc["name"],
            "port": svc["port"],
            "online": online,
        })
    return results

@app.get("/api/portal/research")
def portal_research():
    """List recent research notes from Obsidian vault."""
    research_dir = os.path.join(OBSIDIAN_VAULT, "Research")
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
                       "url": f"/docs/Research/{os.path.basename(f)}"})
    
    # Sort by mtime desc, take 10
    notes.sort(key=lambda x: x["mtime"], reverse=True)
    for n in notes:
        del n["mtime"]
    return notes[:10]

@app.get("/api/portal/kanban")
def portal_kanban():
    """List kanban boards from Obsidian vault."""
    kanban_dir = os.path.join(OBSIDIAN_VAULT, "Kanban")
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
                        "url": f"/docs/Kanban/{os.path.basename(f)}"})
    return boards

@app.get("/api/portal/earlyrise")
def portal_earlyrise():
    """Early Rise summary for portal."""
    streak = _calc_streak()
    with db_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as total, SUM(pass) as passed FROM checkins").fetchone()
    total = row["total"] if row else 0
    passed = row["passed"] if row and row["passed"] else 0
    return {"streak": streak, "total": total, "passed": passed}

# --- Serve Portal Frontend ---
PORTAL_DIR = os.path.join(os.path.dirname(__file__), "..", "portal")
app.mount("/static", StaticFiles(directory=PORTAL_DIR), name="static")

@app.get("/portal")
@app.get("/portal/")
def serve_portal():
    html_path = os.path.join(PORTAL_DIR, "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return JSONResponse({"error": "Portal not found"}, status_code=404)

@app.get("/usage")
@app.get("/usage/")
def serve_usage():
  html_path = os.path.join(PORTAL_DIR, "usage.html")
  if os.path.exists(html_path):
    return FileResponse(html_path)
  return JSONResponse({"error": "Usage page not found"}, status_code=404)

# --- Docs API ---

import markdown as md_lib
from starlette.responses import HTMLResponse

# Allowed dirs (security: only read from these)
DOCS_DIRS = {
    "Bookmarks": os.path.join(OBSIDIAN_VAULT, "Bookmarks"),
    "Kanban": os.path.join(OBSIDIAN_VAULT, "Kanban"),
    "Notes": os.path.join(OBSIDIAN_VAULT, "Notes"),
    "People": os.path.join(OBSIDIAN_VAULT, "People"),
    "PlanPipeline": os.path.join(OBSIDIAN_VAULT, "PlanPipeline"),
    "Research": os.path.join(OBSIDIAN_VAULT, "Research"),
    "TaskLog": os.path.join(OBSIDIAN_VAULT, "TaskLog"),
    "Workspace": os.path.join(OBSIDIAN_VAULT, "Workspace"),
}

def _safe_path(requested_path: str) -> str | None:
    """Resolve path and ensure it's within OBSIDIAN_VAULT."""
    full = os.path.normpath(os.path.join(OBSIDIAN_VAULT, requested_path))
    if not full.startswith(os.path.normpath(OBSIDIAN_VAULT)):
        return None
    return full

@app.get("/api/docs/tree")
def docs_tree():
    """Return folder tree with file counts."""
    result = []
    for name, path in DOCS_DIRS.items():
        if not os.path.isdir(path):
            continue
        files = []
        for f in sorted(glob.glob(os.path.join(path, "*.md"))):
            fname = os.path.splitext(os.path.basename(f))[0]
            mtime = os.path.getmtime(f)
            files.append({"name": fname, "mtime": mtime})
        files.sort(key=lambda x: x["mtime"], reverse=True)
        for f in files:
            del f["mtime"]
        result.append({"folder": name, "files": files})
    return result

@app.get("/api/docs/content")
def docs_content(path: str = ""):
    """Read and render a markdown file. path is relative to vault root."""
    full = _safe_path(path)
    if not full or not os.path.isfile(full):
        raise HTTPException(404, "文件不存在")
    if not full.endswith(".md"):
        full += ".md"

    try:
        with open(full, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        raise HTTPException(500, str(e))

    # Parse frontmatter
    title = os.path.splitext(os.path.basename(full))[0]
    tags = []
    date_str = ""
    content_raw = raw
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', raw, re.DOTALL)
    if fm_match:
        content_raw = fm_match.group(2)
        fm_text = fm_match.group(1)
        tag_m = re.search(r'tags:\s*\[(.*?)\]', fm_text)
        if tag_m:
            tags = [t.strip().strip('"\'') for t in tag_m.group(1).split(",") if t.strip()]
        date_m = re.search(r'date:\s*["\']?(\d{4}-\d{2}-\d{2})', fm_text)
        if date_m:
            date_str = date_m.group(1)

    # Render markdown to HTML
    html_content = md_lib.markdown(
        content_raw,
        extensions=["extra", "codehilite", "toc", "tables", "fenced_code"],
        output_format="html5",
    )

    return {
        "title": title,
        "tags": tags,
        "date": date_str,
        "html": html_content,
        "path": path,
    }

@app.get("/api/docs/search")
def docs_search(q: str = ""):
    """Full-text search across all docs dirs."""
    if not q or len(q) < 2:
        return []
    results = []
    ql = q.lower()
    for name, dir_path in DOCS_DIRS.items():
        if not os.path.isdir(dir_path):
            continue
        for f in glob.glob(os.path.join(dir_path, "*.md")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    content = fh.read(10000).lower()
                if ql in content or ql in os.path.basename(f).lower():
                    fname = os.path.splitext(os.path.basename(f))[0]
                    results.append({
                        "title": fname,
                        "folder": name,
                        "path": os.path.relpath(f, OBSIDIAN_VAULT),
                    })
            except Exception:
                pass
    return results[:20]

# --- Projects API (driven by Notes/*-progress.md) ---
PROJECTS_DIR = os.path.join(OBSIDIAN_VAULT, "Notes")

def _parse_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter from markdown."""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    fm = {}
    for line in text[3:end].strip().split("\n"):
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        elif v.isdigit():
            v = int(v)
        fm[k] = v
    return fm

def _extract_md_section(text: str, heading: str) -> str:
    """Extract content under a ## heading."""
    import re
    m = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""

@app.get("/api/projects")
def get_projects():
    """Return all projects from Notes/*-progress.md frontmatter."""
    import glob as _glob
    projects = []
    for fpath in sorted(_glob.glob(os.path.join(PROJECTS_DIR, "*-progress.md"))):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                text = f.read()
            meta = _parse_frontmatter(text)
            if not meta:
                continue
            # Extract description from 项目定位 section
            desc = _extract_md_section(text, "项目定位").strip("- \n") or ""
            if not desc or desc == "---":
                # Fallback: use first non-empty, non-heading line after frontmatter
                import re
                for line in text.split("\n"):
                    line = line.strip()
                    if line.startswith("---") or line.startswith("#") or line.startswith(">") or not line:
                        continue
                    desc = line
                    break
            # Extract done/todo summaries
            done_sec = ""
            for h in ["已完成 ✅", "已完成", "当前状态", "核心结论"]:
                done_sec = _extract_md_section(text, h)
                if done_sec:
                    break
            import re
            done_items = [re.sub(r"^\s*[-*]\s*", "", l).strip() for l in done_sec.split("\n") if re.match(r"^\s*[-*]\s+", l)]
            todo_sec = _extract_md_section(text, "待办 📋") or _extract_md_section(text, "待办")
            todo_items = [re.sub(r"^\s*[-*]\s*", "", l).strip() for l in todo_sec.split("\n") if re.match(r"^\s*[-*]\s+", l)]
            # Title from first heading
            title_m = re.search(r"^# (.+)$", text, re.MULTILINE)
            meta["title"] = title_m.group(1) if title_m else meta.get("project", "")
            meta["description"] = desc
            meta["done"] = done_items[:8]
            meta["todo"] = todo_items[:6]
            projects.append(meta)
        except Exception:
            pass
    return {"projects": projects}

# Serve docs SPA
@app.get("/docs")
@app.get("/docs/")
@app.get("/docs/{full_path:path}")
def serve_docs(full_path: str = ""):
    html_path = os.path.join(PORTAL_DIR, "docs.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return JSONResponse({"error": "Docs UI not found"}, status_code=404)


# --- Knowledge Graph (standalone module) ---
try:
    from backend.graph import router as graph_router
except ImportError:
    from graph import router as graph_router
app.include_router(graph_router)

@app.get("/graph")
@app.get("/graph/")
def serve_graph():
    html_path = os.path.join(PORTAL_DIR, "graph.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return JSONResponse({"error": "Graph UI not found"}, status_code=404)


# --- Command Actions API (requires auth) ---
import subprocess

# Whitelisted services that can be managed
MANAGED_SERVICES = {
    "discipline": {"type": "launchctl", "plist": "ai.hermes.discipline", "port": 8899},
    "hermes-gateway": {"type": "launchctl", "plist": "ai.hermes.gateway", "port": None},
}

@app.post("/api/actions/restart-service")
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

@app.post("/api/actions/create-note")
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

@app.get("/api/actions/cron-list")
def action_cron_list(request: Request):
    """List available cron jobs for manual trigger."""
    verify_token(request)
    try:
        result = subprocess.run(
            ["python3", os.path.expanduser("~/.hermes/scripts/cron_helper.py"), "list"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            import json
            return json.loads(result.stdout)
        return JSONResponse({"error": result.stderr.strip()}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/actions/cron-jobs")
def action_cron_jobs(request: Request):
    """List cron jobs from Hermes jobs.json (read-only)."""
    verify_token(request)
    jobs_path = os.path.expanduser("~/.hermes/cron/jobs.json")
    if not os.path.exists(jobs_path):
        return []
    try:
        import json
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

@app.post("/api/actions/trigger-cron")
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

@app.get("/api/usage")
def api_usage():
    """Return AI usage data from calibration files."""
    import json, glob
    usage_dir = os.path.expanduser("~/.hermes/usage")
    result = {}
    for f in glob.glob(os.path.join(usage_dir, "*calibration*.json")):
        name = os.path.basename(f).replace(".json", "")
        try:
            with open(f) as fp:
                result[name] = json.load(fp)
        except:
            pass
    return result

# ─── Knowledge Hub API ───────────────────────────────────────────────
import sys as _sys
_sys.path.insert(0, str(Path("~/.hermes/hermes-agent").expanduser()))
try:
    from fastapi import APIRouter as _APIRouter
    from hermes_cli import knowledge as _k
    _KNOWLEDGE_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    _KNOWLEDGE_AVAILABLE = False


if _KNOWLEDGE_AVAILABLE:
    _kr = _APIRouter(prefix="/api/knowledge", tags=["knowledge"])
    _HERMES_HOME = Path("~/.hermes").expanduser()
    _REPO_ROOT = Path(_k.__file__).resolve().parent.parent.parent  # hermes-agent/

    # Simple TTL cache for knowledge index (avoids rebuilding on every request)
    _k_cache: list = []
    _k_cache_ts: float = 0.0
    _K_CACHE_TTL = 60.0  # seconds

    def _kitems():
        global _k_cache, _k_cache_ts
        import time
        now = time.time()
        if _k_cache and (now - _k_cache_ts) < _K_CACHE_TTL:
            return _k_cache
        idx = _k._shared_dir(_HERMES_HOME) / "knowledge_index.jsonl"
        _k_cache = _k._load_or_build(idx, _REPO_ROOT, _HERMES_HOME)
        _k_cache_ts = now
        return _k_cache


    def _item_json(it: _k.KnowledgeItem) -> dict:
        return {
            "id": it.id, "type": it.type, "title": it.title, "summary": it.summary,
            "project": it.project, "tags": it.tags, "sensitivity": it.sensitivity,
            "status": it.status, "updated_at": it.updated_at,
        }


    @_kr.get("/search")
    def knowledge_search(q: str = "", project: str = None, scope: str = None, limit: int = 20):
        items = _kitems()
        results = _k.search_items(items, q, scope=scope, project=project, limit=limit)
        return [_item_json(it) for it in results]


    @_kr.get("/items/{item_id}")
    def knowledge_item(item_id: str):
        items = _kitems()
        item = _k.get_item(items, item_id)
        if item is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        d = _item_json(item)
        try:
            d["content"] = _k.redact_secrets(_k.read_item_content(item))
        except PermissionError:
            d["content"] = "[restricted]"
        return d


    @_kr.get("/decisions")
    def knowledge_decisions(project: str = None, author: str = None):
        decisions = _k.load_decisions(project=project, author=author, hermes_home=_HERMES_HOME)
        return [{
            "id": d.id, "project": d.project, "title": d.title, "author": d.author,
            "body": _k.redact_secrets(d.body), "rationale": _k.redact_secrets(d.rationale),
            "alternatives": _k.redact_secrets(d.alternatives), "tags": d.tags,
            "created_at": d.created_at, "superseded_by": d.superseded_by,
        } for d in decisions]


    @_kr.post("/publish")
    def knowledge_publish(body: dict = None):
        body = body or {}
        p = _k.publish_decision(
            project=body.get("project", ""), title=body.get("title", ""),
            author=body.get("author", ""), body=body.get("body", ""),
            rationale=body.get("rationale", ""), alternatives=body.get("alternatives", ""),
            tags=body.get("tags", []), hermes_home=_HERMES_HOME,
        )
        return {"ok": True, "file": p.name}


    @_kr.get("/experts")
    def knowledge_experts(project: str = None, role: str = None):
        experts = _k.load_experts(project=project, role=role, hermes_home=_HERMES_HOME)
        return [{
            "id": e.id, "role": e.role, "project": e.project,
            "capabilities": e.capabilities, "status": e.status,
            "registered_at": e.registered_at, "last_heartbeat": e.last_heartbeat,
        } for e in experts]


    @_kr.post("/register")
    def knowledge_register(body: dict = None):
        body = body or {}
        _k.register_expert(
            expert_id=body.get("expert_id", ""), role=body.get("role", ""),
            project=body.get("project", ""), capabilities=body.get("capabilities", []),
            hermes_home=_HERMES_HOME,
        )
        return {"ok": True}


    @_kr.post("/heartbeat")
    def knowledge_heartbeat(body: dict = None):
        ok = _k.heartbeat_expert((body or {}).get("expert_id", ""), hermes_home=_HERMES_HOME)
        return {"ok": ok}


    @_kr.post("/deregister")
    def knowledge_deregister(body: dict = None):
        ok = _k.deregister_expert((body or {}).get("expert_id", ""), hermes_home=_HERMES_HOME)
        return {"ok": ok}


    @_kr.get("/blackboard")
    def knowledge_blackboard(project: str = None, category: str = None, limit: int = 20):
        entries = _k.load_blackboard(project=project, category=category, hermes_home=_HERMES_HOME)
        return entries[-limit:]


    @_kr.post("/blackboard")
    def knowledge_blackboard_post(body: dict = None):
        body = body or {}
        p = _k.post_to_blackboard(
            expert_id=body.get("expert_id", ""), project=body.get("project", ""),
            category=body.get("category", "note"), title=body.get("title", ""),
            body=body.get("body", ""), hermes_home=_HERMES_HOME,
        )
        return {"ok": True, "file": p.name}


    @_kr.get("/report")
    def knowledge_report(project: str = "", role: str = None):
        report = _k.generate_context_report(
            project=project, role=role, hermes_home=_HERMES_HOME,
        )
        return {"report": _k.redact_secrets(report)}


    app.include_router(_kr)

@app.get("/knowledge")
@app.get("/knowledge/")
def serve_knowledge():
    html = os.path.join(PORTAL_DIR, "knowledge.html")
    if os.path.exists(html):
        return FileResponse(html)
    return JSONResponse({"error": "knowledge.html not found"}, status_code=404)

# ─── End Knowledge Hub API ───────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8899)))