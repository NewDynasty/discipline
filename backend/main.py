"""Discipline Command Center — FastAPI main entry point.

Pure orchestrator: app creation + router registration + static mount.
All business logic lives in routers/.
"""
import os
import sys

# Ensure backend dir is in path
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from deps import init_db, PORTAL_DIR

# --- App ---
app = FastAPI(title="Discipline Command Center", version="3.0.0", docs_url=None, redoc_url=None)


@app.on_event("startup")
def startup():
    init_db()


# --- Core routers (always loaded) ---
from routers.portal import router as portal_router
from routers.docs import router as docs_router
from routers.actions import router as actions_router
from routers.checkin import router as checkin_router
from routers.proxy import router as proxy_router

app.include_router(portal_router)
app.include_router(docs_router)
app.include_router(actions_router)
app.include_router(checkin_router)
app.include_router(proxy_router)

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
