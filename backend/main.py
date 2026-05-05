"""Discipline Command Center — FastAPI main entry point."""
import os
import sys
from pathlib import Path

# Ensure backend dir is in path for router imports
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from deps import DB_PATH, PORTAL_DIR, init_db, db_conn, verify_token
from deps import LoginRequest, CheckinRequest, CheckinResponse, StatsResponse

# --- App ---
app = FastAPI(title="Discipline Command Center", version="2.0.0", docs_url=None, redoc_url=None)

@app.on_event("startup")
def startup():
    init_db()

# --- Include Routers ---
from routers.portal import router as portal_router
from routers.docs import router as docs_router
from routers.actions import router as actions_router

app.include_router(portal_router)
app.include_router(docs_router)
app.include_router(actions_router)

# --- Early Rise API (checkin/stats) ---
# These stay inline because they're tightly coupled with auth flow
import secrets
from datetime import date, datetime, timedelta
from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response):
    if req.password != os.environ.get("EARLYRISE_TOKEN", "earlyrise2026"):
        raise HTTPException(403, "Wrong password")
    token = secrets.token_hex(16)
    expires = datetime.utcnow() + timedelta(hours=int(os.environ.get("TOKEN_EXPIRE_HOURS", "168")))
    with db_conn() as conn:
        conn.execute("INSERT INTO tokens (token, expires_at) VALUES (?, ?)", (token, expires.isoformat()))
    response.set_cookie("token", token, httponly=True, max_age=int(os.environ.get("TOKEN_EXPIRE_HOURS", "168")) * 3600)
    return {"token": token}

@app.post("/api/auth/logout")
def logout(request: Request):
    token = request.cookies.get("token", "")
    if token:
        with db_conn() as conn:
            conn.execute("DELETE FROM tokens WHERE token=?", (token,))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("token")
    return resp

@app.post("/api/checkin", response_model=CheckinResponse)
def create_checkin(req: CheckinRequest, _=Depends(verify_token)):
    today = date.today().isoformat()
    h, m = map(int, req.wake_time.split(":"))
    passed = 1 if h < 6 or (h == 6 and m == 0) else 0
    with db_conn() as conn:
        existing = conn.execute("SELECT date FROM checkins WHERE date=?", (today,)).fetchone()
        if existing:
            conn.execute("UPDATE checkins SET wake_time=?, pass=?, updated_at=datetime('now') WHERE date=?",
                         (req.wake_time, passed, today))
        else:
            conn.execute("INSERT INTO checkins (date, wake_time, pass) VALUES (?,?,?)",
                         (today, req.wake_time, passed))
        from deps import _calc_streak
        streak = _calc_streak()
    return CheckinResponse(date=today, wake_time=req.wake_time, pass_=bool(passed), streak=streak)

@app.get("/api/checkin/today")
def get_today(_=Depends(verify_token)):
    today = date.today().isoformat()
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM checkins WHERE date=?", (today,)).fetchone()
    if not row:
        return {"checked_in": False}
    return {"checked_in": True, "date": row["date"], "wake_time": row["wake_time"], "pass": row["pass"]}

@app.get("/api/stats", response_model=StatsResponse)
def get_stats(_=Depends(verify_token)):
    from deps import _calc_streak
    with db_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0]
        pass_count = conn.execute("SELECT COUNT(*) FROM checkins WHERE pass=1").fetchone()[0]
        fail_count = total - pass_count
        avg = conn.execute("SELECT AVG(CAST(substr(wake_time,1,2) AS REAL)*60 + CAST(substr(wake_time,4,2) AS REAL)) FROM checkins").fetchone()[0]
        best = conn.execute("SELECT MIN(wake_time) FROM checkins").fetchone()[0]
    avg_str = f"{int(avg//60):02d}:{int(avg%60):02d}" if avg else None
    return StatsResponse(streak=_calc_streak(), total=total, pass_count=pass_count,
                         fail_count=fail_count, avg_time=avg_str, best_time=best,
                         rate=round(pass_count/total, 2) if total else 0)

@app.get("/api/records")
def get_records(days: int = 30, _=Depends(verify_token)):
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM checkins ORDER BY date DESC LIMIT ?", (days,)).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/heatmap")
def get_heatmap(_=Depends(verify_token)):
    with db_conn() as conn:
        rows = conn.execute("SELECT date, pass FROM checkins ORDER BY date").fetchall()
    return [dict(r) for r in rows]

# --- Root redirect ---
@app.get("/")
def serve_index():
    return RedirectResponse(url="/portal")

# --- Static files ---
app.mount("/static", StaticFiles(directory=PORTAL_DIR), name="static")

# --- Knowledge Graph (conditional, needs hermes_cli) ---
try:
    from graph import router as graph_router
    app.include_router(graph_router)
except ImportError:
    pass

# --- Knowledge API (standalone lite, no hermes_cli needed) ---
import sys as _sys
_KNOWLEDGE_AVAILABLE = False
try:
    import knowledge_lite as _k
    from fastapi import APIRouter as _APIRouter
    _KNOWLEDGE_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    _KNOWLEDGE_AVAILABLE = False


if _KNOWLEDGE_AVAILABLE:
    _kr = _APIRouter(prefix="/api/knowledge", tags=["knowledge"])
    _HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path("~/.hermes").expanduser()))).resolve()
    _REPO_ROOT = Path(__file__).resolve().parent.parent.parent

    _k_cache: list = []
    _k_cache_ts: float = 0.0
    _K_CACHE_TTL = 60.0

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
    html_path = os.path.join(PORTAL_DIR, "knowledge.html")
    return FileResponse(html_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

# --- Dev server ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8899")))
