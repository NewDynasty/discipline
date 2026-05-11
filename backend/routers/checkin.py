"""Auth + Checkin API — login/logout, checkin, stats, records, heatmap, webhook."""
import os
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from deps import (db_conn, verify_token, _calc_streak, TOKEN_EXPIRE_HOURS,
                  LoginRequest, CheckinRequest, CheckinResponse, StatsResponse)

router = APIRouter(tags=["checkin"])


# ── Auth ──────────────────────────────────────────────────────────────────────

@router.post("/api/auth/login")
def login(req: LoginRequest, response: Response):
    if req.password != os.environ.get("EARLYRISE_TOKEN", "earlyrise2026"):
        raise HTTPException(403, "Wrong password")
    token = secrets.token_hex(16)
    expires = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    with db_conn() as conn:
        conn.execute("INSERT INTO tokens (token, expires_at) VALUES (?, ?)", (token, expires.isoformat()))
    response.set_cookie("token", token, httponly=True, max_age=TOKEN_EXPIRE_HOURS * 3600)
    return {"token": token}


@router.post("/api/auth/logout")
def logout(request: Request):
    token = request.cookies.get("token", "")
    if token:
        with db_conn() as conn:
            conn.execute("DELETE FROM tokens WHERE token=?", (token,))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("token")
    return resp


# ── Checkin ───────────────────────────────────────────────────────────────────

@router.post("/api/checkin", response_model=CheckinResponse)
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
        streak = _calc_streak()
    return CheckinResponse(date=today, wake_time=req.wake_time, pass_=bool(passed), streak=streak)


@router.get("/api/checkin/today")
def get_today(_=Depends(verify_token)):
    today = date.today().isoformat()
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM checkins WHERE date=?", (today,)).fetchone()
    if not row:
        return {"checked_in": False}
    return {"checked_in": True, "date": row["date"], "wake_time": row["wake_time"], "pass": row["pass"]}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/api/stats", response_model=StatsResponse)
def get_stats(_=Depends(verify_token)):
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


@router.get("/api/records")
def get_records(days: int = 30, _=Depends(verify_token)):
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM checkins ORDER BY date DESC LIMIT ?", (days,)).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/heatmap")
def get_heatmap(_=Depends(verify_token)):
    with db_conn() as conn:
        rows = conn.execute("SELECT date, pass FROM checkins ORDER BY date").fetchall()
    return [dict(r) for r in rows]


# ── Webhook (machine-to-machine, API key auth) ─────────────────────────────

WEBHOOK_API_KEY=os.environ.get("DISCIPLINE_WEBHOOK_KEY", "")

def _verify_webhook(request: Request):
    """Verify webhook via X-API-Key header or api_key query param."""
    api_key = request.headers.get("X-API-Key", "") or request.query_params.get("api_key", "")
    if not WEBHOOK_API_KEY:
        raise HTTPException(500, "DISCIPLINE_WEBHOOK_KEY not configured")
    if api_key != WEBHOOK_API_KEY:
        raise HTTPException(403, "Invalid API key")


@router.post("/api/webhook/checkin")
async def webhook_checkin(request: Request, _=Depends(_verify_webhook)):
    """Auto checkin from external triggers (HA, Hermes, iOS shortcuts).

    Accepts optional JSON body:
    - wake_time (str): HH:MM, defaults to current time
    - source (str): origin label, e.g. "apple-watch", "ha-automation"

    Returns checkin result with streak info.
    """
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        body = {}

    now = datetime.now()
    wake_time = body.get("wake_time", now.strftime("%H:%M"))
    source = body.get("source", "webhook")

    # Validate HH:MM format
    try:
        parts = wake_time.split(":")
        h, m = int(parts[0]), int(parts[1])
        assert 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        raise HTTPException(400, f"Invalid wake_time: {wake_time}, expected HH:MM")

    today = date.today().isoformat()
    passed = 1 if h < 6 or (h == 6 and m == 0) else 0

    with db_conn() as conn:
        existing = conn.execute("SELECT date FROM checkins WHERE date=?", (today,)).fetchone()
        if existing:
            conn.execute("UPDATE checkins SET wake_time=?, pass=?, updated_at=datetime('now') WHERE date=?",
                         (wake_time, passed, today))
        else:
            conn.execute("INSERT INTO checkins (date, wake_time, pass) VALUES (?,?,?)",
                         (today, wake_time, passed))
        streak = _calc_streak()

    return {
        "ok": True,
        "date": today,
        "wake_time": wake_time,
        "pass": bool(passed),
        "streak": streak,
        "source": source,
    }


@router.post("/api/webhook/health")
async def webhook_health(request: Request, _=Depends(_verify_webhook)):
    """Receive health data from Apple Watch / HA.

    Accepts JSON body:
    - type (str): "sleep", "heart_rate", "steps", "workout"
    - data (dict): the health payload
    - timestamp (str, optional): ISO timestamp

    Currently logs and returns acknowledgement.
    Future: store in health_data table, trigger automations.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    health_type = body.get("type", "unknown")
    health_data = body.get("data", {})
    ts = body.get("timestamp", datetime.now().isoformat())

    # TODO: store in health_data table when ready
    # For now, just acknowledge
    return {
        "ok": True,
        "received": {
            "type": health_type,
            "data": health_data,
            "timestamp": ts,
        },
    }
