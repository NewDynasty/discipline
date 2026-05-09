"""Shared configuration, database, auth, and models for all routers."""
import os
import sqlite3
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel

# --- Config ---
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("EARLY_RISE_DB", os.path.join(_BACKEND_DIR, "data", "earlyrise.db"))
SECRET_TOKEN = os.environ.get("EARLYRISE_TOKEN", "earlyrise2026")
OBSIDIAN_VAULT = os.environ.get("OBSIDIAN_VAULT", os.path.expanduser("~/Documents/Obsidian Vault"))
PORTAL_DIR = os.path.join(os.path.dirname(_BACKEND_DIR), "portal")

# --- Portal Registry ---
def load_portal_registry() -> dict:
    """Load portal-registry.yaml from portal dir. Requires PyYAML."""
    reg_path = os.path.join(PORTAL_DIR, "portal-registry.yaml")
    if not os.path.exists(reg_path):
        return {"systems": [], "services": []}
    try:
        import yaml
        with open(reg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"systems": [], "services": []}
    except ImportError:
        # Fallback: return empty if PyYAML not installed
        return {"systems": [], "services": []}

PORTAL_REGISTRY = load_portal_registry()

# --- Vault Registry ---
def load_vault_registry() -> dict:
    """Load vault-registry.yaml from vault root. No external deps needed."""
    import re
    reg_path = os.path.join(OBSIDIAN_VAULT, "vault-registry.yaml")
    if not os.path.exists(reg_path):
        return {}
    with open(reg_path, "r", encoding="utf-8") as f:
        text = f.read()
    # Minimal YAML parser for our flat config structure
    result = {}
    current_section = None  # e.g. "projects"
    current_sub = None      # e.g. "dirs" (list key under section)
    for raw_line in text.split('\n'):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(line) - len(line.lstrip())
        # Top-level keys (no indent)
        if indent == 0:
            m = re.match(r'^(\w+):\s*(.*)', stripped)
            if m:
                key = m.group(1)
                val = m.group(2).strip().strip('"')
                if val:
                    result[key] = val
                    current_section = None
                else:
                    result[key] = {}
                    current_section = key
                current_sub = None
            continue
        # Sub-keys (2-space indent)
        if current_section and indent == 2:
            m = re.match(r'^(\w+):\s*(.*)', stripped)
            if m:
                current_sub = m.group(1)
                val = m.group(2).strip().strip('"')
                if val:
                    result[current_section][current_sub] = val
                else:
                    result[current_section][current_sub] = []
            continue
        # List items (4+ space indent, starting with "- ")
        if current_section and current_sub and indent >= 4 and stripped.startswith('- '):
            val = stripped[2:].strip().strip('"\'')
            if isinstance(result[current_section].get(current_sub), list):
                result[current_section][current_sub].append(val)
    return result

VAULT_REGISTRY = load_vault_registry()
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
        raise HTTPException(401, "\u672a\u767b\u5f55")
    
    with db_conn() as conn:
        row = conn.execute(
            "SELECT expires_at FROM tokens WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            raise HTTPException(401, "\u65e0\u6548 token")
        expires = datetime.fromisoformat(row["expires_at"])
        if datetime.utcnow() > expires:
            conn.execute("DELETE FROM tokens WHERE token = ?", (token,))
            raise HTTPException(401, "token \u5df2\u8fc7\u671f")
    
    return True

# --- Pydantic Models ---
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

# --- Helpers ---
def _calc_streak() -> int:
    from datetime import date, timedelta
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

# --- Environment detection ---
def detect_env() -> dict:
    """Unified runtime environment check. Call once at startup if needed."""
    import importlib
    env = {
        "is_cloud": not os.path.exists("/Users/"),
        "has_vault": os.path.isdir(OBSIDIAN_VAULT),
    }
    # Check optional module availability
    for mod in ("knowledge_lite", "graph", "httpx"):
        try:
            importlib.import_module(mod)
            env[f"has_{mod}"] = True
        except ImportError:
            env[f"has_{mod}"] = False
    return env

ENV = detect_env()
