"""Auth + Checkin API — login/logout, checkin, stats, records, heatmap."""
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
