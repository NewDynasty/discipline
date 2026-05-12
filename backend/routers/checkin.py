"""Auth + Checkin API — login/logout, checkin (wake/sleep/exercise), stats, records, heatmap."""
import os
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from deps import (db_conn, verify_token, _calc_streak, TOKEN_EXPIRE_HOURS,
                  LoginRequest, CheckinRequest, SleepCheckinRequest,
                  ExerciseCheckinRequest, CheckinResponse, StatsResponse)

router = APIRouter(tags=["checkin"])

# ── 合法的打卡类型 ──
VALID_TYPES = {"wake", "sleep", "exercise"}


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


# ── Checkin: 早起 ─────────────────────────────────────────────────────────────

@router.post("/api/checkin", response_model=CheckinResponse)
def create_checkin(req: CheckinRequest, _=Depends(verify_token)):
    """早起打卡 — 6:00 及之前为达标"""
    today = date.today().isoformat()
    h, m = map(int, req.wake_time.split(":"))
    passed = 1 if h < 8 or (h == 8 and m == 0) else 0
    with db_conn() as conn:
        existing = conn.execute(
            "SELECT date FROM checkins WHERE date=? AND checkin_type='wake'", (today,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE checkins SET wake_time=?, pass=?, updated_at=datetime('now') WHERE date=? AND checkin_type='wake'",
                (req.wake_time, passed, today))
        else:
            conn.execute(
                "INSERT INTO checkins (date, checkin_type, wake_time, pass) VALUES (?,?,?,?)",
                (today, "wake", req.wake_time, passed))
        streak = _calc_streak("wake")
    return CheckinResponse(date=today, checkin_type="wake", wake_time=req.wake_time,
                           pass_=bool(passed), streak=streak)


# ── Checkin: 早睡 ─────────────────────────────────────────────────────────────

@router.post("/api/checkin/sleep", response_model=CheckinResponse)
def create_sleep_checkin(req: SleepCheckinRequest, _=Depends(verify_token)):
    """早睡打卡 — 目标时间及之前为达标"""
    today = date.today().isoformat()
    h, m = map(int, req.sleep_time.split(":"))
    th, tm = map(int, req.target_time.split(":"))
    sleep_mins = h * 60 + m
    target_mins = th * 60 + tm
    passed = 1 if sleep_mins <= target_mins else 0
    with db_conn() as conn:
        existing = conn.execute(
            "SELECT date FROM checkins WHERE date=? AND checkin_type='sleep'", (today,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE checkins SET sleep_time=?, pass=?, updated_at=datetime('now') WHERE date=? AND checkin_type='sleep'",
                (req.sleep_time, passed, today))
        else:
            conn.execute(
                "INSERT INTO checkins (date, checkin_type, sleep_time, pass) VALUES (?,?,?,?)",
                (today, "sleep", req.sleep_time, passed))
        streak = _calc_streak("sleep")
    return CheckinResponse(date=today, checkin_type="sleep", sleep_time=req.sleep_time,
                           pass_=bool(passed), streak=streak)


# ── Checkin: 运动 ─────────────────────────────────────────────────────────────

@router.post("/api/checkin/exercise", response_model=CheckinResponse)
def create_exercise_checkin(req: ExerciseCheckinRequest, _=Depends(verify_token)):
    """运动打卡 — 运动30分钟及以上为达标"""
    today = date.today().isoformat()
    passed = 1 if req.duration >= 30 else 0
    with db_conn() as conn:
        existing = conn.execute(
            "SELECT date FROM checkins WHERE date=? AND checkin_type='exercise'", (today,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE checkins SET exercise_type=?, exercise_duration=?, pass=?, updated_at=datetime('now') "
                "WHERE date=? AND checkin_type='exercise'",
                (req.exercise_type, req.duration, passed, today))
        else:
            conn.execute(
                "INSERT INTO checkins (date, checkin_type, exercise_type, exercise_duration, pass) VALUES (?,?,?,?,?)",
                (today, "exercise", req.exercise_type, req.duration, passed))
        streak = _calc_streak("exercise")
    return CheckinResponse(date=today, checkin_type="exercise", exercise_type=req.exercise_type,
                           exercise_duration=req.duration, pass_=bool(passed), streak=streak)


# ── Today status ──────────────────────────────────────────────────────────────

@router.get("/api/checkin/today")
def get_today(_=Depends(verify_token)):
    today = date.today().isoformat()
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM checkins WHERE date=?", (today,)
        ).fetchall()
    if not rows:
        return {"checked_in": False, "types": []}
    result = {"checked_in": True, "date": today, "types": []}
    for row in rows:
        entry = {"checkin_type": row["checkin_type"], "pass": bool(row["pass"])}
        if row["checkin_type"] == "wake":
            entry["wake_time"] = row["wake_time"]
        elif row["checkin_type"] == "sleep":
            entry["sleep_time"] = row["sleep_time"]
        elif row["checkin_type"] == "exercise":
            entry["exercise_type"] = row["exercise_type"]
            entry["exercise_duration"] = row["exercise_duration"]
        result["types"].append(entry)
    return result


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/api/stats", response_model=StatsResponse)
def get_stats(checkin_type: str = "wake", _=Depends(verify_token)):
    """统计面板，默认显示早起数据，可通过 checkin_type 参数切换"""
    if checkin_type not in VALID_TYPES:
        raise HTTPException(400, f"Invalid type, must be one of {VALID_TYPES}")

    with db_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM checkins WHERE checkin_type=?", (checkin_type,)
        ).fetchone()[0]
        pass_count = conn.execute(
            "SELECT COUNT(*) FROM checkins WHERE checkin_type=? AND pass=1", (checkin_type,)
        ).fetchone()[0]
        fail_count = total - pass_count

        # 根据类型计算不同的统计字段
        if checkin_type == "wake":
            avg = conn.execute(
                "SELECT AVG(CAST(substr(wake_time,1,2) AS REAL)*60 + CAST(substr(wake_time,4,2) AS REAL)) "
                "FROM checkins WHERE checkin_type='wake'"
            ).fetchone()[0]
            best = conn.execute(
                "SELECT MIN(wake_time) FROM checkins WHERE checkin_type='wake'"
            ).fetchone()[0]
            avg_str = f"{int(avg//60):02d}:{int(avg%60):02d}" if avg else None
        elif checkin_type == "sleep":
            avg = conn.execute(
                "SELECT AVG(CAST(substr(sleep_time,1,2) AS REAL)*60 + CAST(substr(sleep_time,4,2) AS REAL)) "
                "FROM checkins WHERE checkin_type='sleep'"
            ).fetchone()[0]
            best = conn.execute(
                "SELECT MIN(sleep_time) FROM checkins WHERE checkin_type='sleep'"
            ).fetchone()[0]
            avg_str = f"{int(avg//60):02d}:{int(avg%60):02d}" if avg else None
        else:  # exercise
            avg = conn.execute(
                "SELECT AVG(exercise_duration) FROM checkins WHERE checkin_type='exercise'"
            ).fetchone()[0]
            best = conn.execute(
                "SELECT MAX(exercise_duration) FROM checkins WHERE checkin_type='exercise'"
            ).fetchone()[0]
            avg_str = f"{int(avg)}分钟" if avg else None
            best = f"{best}分钟" if best else None

    return StatsResponse(
        streak=_calc_streak(checkin_type),
        total=total,
        pass_count=pass_count,
        fail_count=fail_count,
        avg_time=avg_str,
        best_time=best,
        rate=round(pass_count / total, 2) if total else 0
    )


@router.get("/api/records")
def get_records(days: int = 30, checkin_type: str = None, _=Depends(verify_token)):
    """历史记录，可选按类型过滤"""
    with db_conn() as conn:
        if checkin_type and checkin_type in VALID_TYPES:
            rows = conn.execute(
                "SELECT * FROM checkins WHERE checkin_type=? ORDER BY date DESC LIMIT ?",
                (checkin_type, days)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM checkins ORDER BY date DESC LIMIT ?", (days,)
            ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/heatmap")
def get_heatmap(checkin_type: str = "wake", _=Depends(verify_token)):
    """热力图数据，默认显示早起"""
    if checkin_type not in VALID_TYPES:
        checkin_type = "wake"
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT date, pass FROM checkins WHERE checkin_type=? ORDER BY date",
            (checkin_type,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Webhook (HA / iOS 快捷指令) ───────────────────────────────────────────────

WEBHOOK_API_KEY = os.environ.get("DISCIPLINE_WEBHOOK_KEY", "")


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
    """
    try:
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        body = {}

    now = datetime.now()
    wake_time = body.get("wake_time", now.strftime("%H:%M"))
    source = body.get("source", "webhook")

    try:
        parts = wake_time.split(":")
        h, m = int(parts[0]), int(parts[1])
        assert 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        raise HTTPException(400, f"Invalid wake_time: {wake_time}, expected HH:MM")

    today = date.today().isoformat()
    passed = 1 if h < 8 or (h == 8 and m == 0) else 0

    with db_conn() as conn:
        existing = conn.execute(
            "SELECT date FROM checkins WHERE date=? AND checkin_type='wake'", (today,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE checkins SET wake_time=?, pass=?, updated_at=datetime('now') WHERE date=? AND checkin_type='wake'",
                (wake_time, passed, today))
        else:
            conn.execute(
                "INSERT INTO checkins (date, checkin_type, wake_time, pass) VALUES (?,?,?,?)",
                (today, "wake", wake_time, passed))
        streak = _calc_streak("wake")

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
    return {
        "ok": True,
        "received": {
            "type": health_type,
            "data": health_data,
            "timestamp": ts,
        },
    }
