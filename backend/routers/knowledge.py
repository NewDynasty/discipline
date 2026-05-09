"""Knowledge API — search, decisions, experts, blackboard, context reports.

Conditionally loaded: only registers routes if knowledge_lite module is available.
"""
import os
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

# Conditional import — if knowledge_lite not available, router stays empty
try:
    import knowledge_lite as _k
    _AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    _AVAILABLE = False

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

if _AVAILABLE:
    _HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path("~/.hermes").expanduser()))).resolve()
    _REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

    # In-memory cache
    _cache: list = []
    _cache_ts: float = 0.0
    _CACHE_TTL = 60.0

    def _items():
        global _cache, _cache_ts
        now = time.time()
        if _cache and (now - _cache_ts) < _CACHE_TTL:
            return _cache
        idx = _k._shared_dir(_HERMES_HOME) / "knowledge_index.jsonl"
        _cache = _k._load_or_build(idx, _REPO_ROOT, _HERMES_HOME)
        _cache_ts = now
        return _cache

    def _item_json(it: _k.KnowledgeItem) -> dict:
        return {
            "id": it.id, "type": it.type, "title": it.title, "summary": it.summary,
            "project": it.project, "tags": it.tags, "sensitivity": it.sensitivity,
            "status": it.status, "updated_at": it.updated_at,
        }

    @router.get("/search")
    def knowledge_search(q: str = "", project: str = None, scope: str = None, limit: int = 20):
        items = _items()
        results = _k.search_items(items, q, scope=scope, project=project, limit=limit)
        return [_item_json(it) for it in results]

    @router.get("/items/{item_id}")
    def knowledge_item(item_id: str):
        items = _items()
        item = _k.get_item(items, item_id)
        if item is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        d = _item_json(item)
        try:
            d["content"] = _k.redact_secrets(_k.read_item_content(item))
        except PermissionError:
            d["content"] = "[restricted]"
        return d

    @router.get("/decisions")
    def knowledge_decisions(project: str = None, author: str = None):
        decisions = _k.load_decisions(project=project, author=author, hermes_home=_HERMES_HOME)
        return [{
            "id": d.id, "project": d.project, "title": d.title, "author": d.author,
            "body": _k.redact_secrets(d.body), "rationale": _k.redact_secrets(d.rationale),
            "alternatives": _k.redact_secrets(d.alternatives), "tags": d.tags,
            "created_at": d.created_at, "superseded_by": d.superseded_by,
        } for d in decisions]

    @router.post("/publish")
    def knowledge_publish(body: dict = None):
        body = body or {}
        p = _k.publish_decision(
            project=body.get("project", ""), title=body.get("title", ""),
            author=body.get("author", ""), body=body.get("body", ""),
            rationale=body.get("rationale", ""), alternatives=body.get("alternatives", ""),
            tags=body.get("tags", []), hermes_home=_HERMES_HOME,
        )
        return {"ok": True, "file": p.name}

    @router.get("/experts")
    def knowledge_experts(project: str = None, role: str = None):
        experts = _k.load_experts(project=project, role=role, hermes_home=_HERMES_HOME)
        return [{
            "id": e.id, "role": e.role, "project": e.project,
            "capabilities": e.capabilities, "status": e.status,
            "registered_at": e.registered_at, "last_heartbeat": e.last_heartbeat,
        } for e in experts]

    @router.post("/register")
    def knowledge_register(body: dict = None):
        body = body or {}
        _k.register_expert(
            expert_id=body.get("expert_id", ""), role=body.get("role", ""),
            project=body.get("project", ""), capabilities=body.get("capabilities", []),
            hermes_home=_HERMES_HOME,
        )
        return {"ok": True}

    @router.post("/heartbeat")
    def knowledge_heartbeat(body: dict = None):
        ok = _k.heartbeat_expert((body or {}).get("expert_id", ""), hermes_home=_HERMES_HOME)
        return {"ok": ok}

    @router.post("/deregister")
    def knowledge_deregister(body: dict = None):
        ok = _k.deregister_expert((body or {}).get("expert_id", ""), hermes_home=_HERMES_HOME)
        return {"ok": ok}

    @router.get("/blackboard")
    def knowledge_blackboard(project: str = None, category: str = None, limit: int = 20):
        entries = _k.load_blackboard(project=project, category=category, hermes_home=_HERMES_HOME)
        return entries[-limit:]

    @router.post("/blackboard")
    def knowledge_blackboard_post(body: dict = None):
        body = body or {}
        p = _k.post_to_blackboard(
            expert_id=body.get("expert_id", ""), project=body.get("project", ""),
            category=body.get("category", "note"), title=body.get("title", ""),
            body=body.get("body", ""), hermes_home=_HERMES_HOME,
        )
        return {"ok": True, "file": p.name}

    @router.get("/report")
    def knowledge_report(project: str = "", role: str = None):
        report = _k.generate_context_report(
            project=project, role=role, hermes_home=_HERMES_HOME,
        )
        return {"report": _k.redact_secrets(report)}
