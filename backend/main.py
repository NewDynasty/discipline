"""Discipline Command Center — FastAPI main entry point.

Pure orchestrator: app creation + router registration + static mount.
All business logic lives in routers/.

Environment variables:
  API_UPSTREAM — if set, all /api/* requests are proxied to this URL (e.g. https://junethebest.cn)
                  and local DB/routers are skipped. Used for local dev proxying to cloud.
"""
import os
import sys

# Ensure backend dir is in path
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles

from deps import PORTAL_DIR

_API_UPSTREAM = os.environ.get("API_UPSTREAM", "").rstrip("/")

# Prefixes that must be served locally (depend on local files / Vault)
_LOCAL_API_PREFIXES = ("/api/docs", "/api/portal", "/api/knowledge", "/api/heatmap")

# --- App ---
app = FastAPI(title="Discipline Command Center", version="3.0.0", docs_url=None, redoc_url=None)


# --- Core routers (always loaded, registered BEFORE proxy catch-all) ---
from routers.portal import router as portal_router
from routers.docs import router as docs_router
from routers.actions import router as actions_router
from routers.proxy import router as proxy_router

app.include_router(portal_router)
app.include_router(docs_router)
app.include_router(actions_router)
app.include_router(proxy_router)


# --- API proxy mode (local dev → cloud) ---
if _API_UPSTREAM:
    try:
        import httpx
        _proxy_client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)

        @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
        async def proxy_api(path: str, request: Request):
            # Let local routers handle Vault-dependent endpoints
            full_path = f"/api/{path}"
            if any(full_path == p or full_path.startswith(p + "/") for p in _LOCAL_API_PREFIXES):
                # FastAPI already matched local routes above; if we reach here,
                # it means no local route matched — fall through to cloud anyway
                pass
            target = f"{_API_UPSTREAM}/api/{path}"
            if request.url.query:
                target += f"?{request.url.query}"
            try:
                resp = await _proxy_client.request(
                    method=request.method,
                    url=target,
                    headers={k: v for k, v in request.headers.items() if k.lower() not in ("host",)},
                    content=await request.body(),
                )
                resp_headers = {k: v for k, v in resp.headers.items()
                                if k.lower() not in ("content-encoding", "transfer-encoding", "content-length")}
                return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers)
            except (httpx.ConnectError, httpx.TimeoutException):
                return JSONResponse({"error": "Cloud API unavailable", "upstream": _API_UPSTREAM}, status_code=502)

        @app.on_event("shutdown")
        async def shutdown_proxy():
            await _proxy_client.aclose()

        print(f"[proxy] API requests → {_API_UPSTREAM}")
    except ImportError:
        print("[warn] httpx not installed, API proxy disabled")
        _API_UPSTREAM = None

# --- Local mode (cloud or no httpx) ---
if not _API_UPSTREAM:
    from deps import init_db

    @app.on_event("startup")
    def startup():
        init_db()

    from routers.checkin import router as checkin_router
    app.include_router(checkin_router)

# --- Optional routers (conditional) ---
try:
    from routers.knowledge import router as knowledge_router
    app.include_router(knowledge_router)
except ImportError:
    pass

try:
    from graph import router as graph_router
    app.include_router(graph_router)
except ImportError:
    pass

# --- Root redirect ---
@app.get("/")
def serve_index():
    return RedirectResponse(url="/portal")

# --- Static files (must be last — catches all unmatched /static/*) ---
app.mount("/static", StaticFiles(directory=PORTAL_DIR), name="static")

# --- Dev server ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8899")))
