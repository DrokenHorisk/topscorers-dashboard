#backend/app/main.py
import os
import asyncio
import signal
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool
from .dashboard_runner import generate_dashboard, OUTPUT_PATH
from .live_service import get_live_snapshot
from .bid_service import list_bids, save_bid, update_result

app = FastAPI(title="TopScorers Backend")

# --------- API ----------
@app.get("/healthz")
@app.get("/api/healthz")
def healthz():
    return {"status": "ok", "last_dashboard_ts": "..."}

@app.post("/api/generate")
def api_generate():
    try:
        path = generate_dashboard()
        return {"ok": True, "file": path}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/live")
async def api_live():
    # Les appels TopScorers sont bloquants : ils tournent hors de la boucle FastAPI.
    return await run_in_threadpool(get_live_snapshot)


class BidCreate(BaseModel):
    player_name: str
    player_id: int | None = None
    team: str = ""
    position_family: str = ""
    market_price: float = Field(gt=0)
    bid_amount: float = Field(gt=0)
    result: str = "pending"
    final_price: float | None = None
    notes: str = ""


class BidResult(BaseModel):
    result: str
    final_price: float | None = None
    notes: str | None = None


@app.get("/api/bids")
def api_bids():
    return {"ok": True, "items": list_bids()}


@app.post("/api/bids")
def api_create_bid(bid: BidCreate):
    return {"ok": True, "item": save_bid(bid.model_dump())}


@app.patch("/api/bids/{bid_id}")
def api_update_bid(bid_id: str, result: BidResult):
    item = update_result(bid_id, result.result, result.final_price, result.notes)
    if item is None:
        raise HTTPException(404, "Enchère introuvable")
    return {"ok": True, "item": item}

@app.get("/api/dashboard")
def api_dashboard():
    if OUTPUT_PATH.exists():
        return FileResponse(str(OUTPUT_PATH), media_type="text/html")
    return PlainTextResponse("Dashboard not generated yet. POST /api/generate", status_code=404)

@app.get("/api/health")
def health():
    return {"status": "ok", "last_dashboard_ts": "..."}

# --------- Scheduler interne ----------
_bg_task = None
_stop = asyncio.Event()

async def _periodic_generator():
    interval_h = float(os.getenv("AUTO_GENERATE_INTERVAL_HOURS", "3"))
    interval_s = max(300, int(interval_h * 3600))  # minimum 5 min de sécurité
    on_start = os.getenv("AUTO_GENERATE_ON_START", "1").strip().lower() in ("1","true","yes","on")

    # génération au démarrage si demandé
    if on_start:
        try:
            p = generate_dashboard()
            print(f"[scheduler] First generation OK -> {p}")
        except Exception as e:
            print(f"[scheduler] First generation FAILED: {e}")

    while not _stop.is_set():
        try:
            # attente interruptible
            try:
                await asyncio.wait_for(_stop.wait(), timeout=interval_s)
                break
            except asyncio.TimeoutError:
                pass

            p = generate_dashboard()
            print(f"[scheduler] Periodic generation OK -> {p}")
        except Exception as e:
            print(f"[scheduler] Periodic generation FAILED: {e}")

@app.on_event("startup")
async def _on_startup():
    global _bg_task
    _bg_task = asyncio.create_task(_periodic_generator())

    # gestion arrêt gracieux si uvicorn passe les signaux
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop.set)
        except NotImplementedError:
            # Windows/containers sans signaux -> ignoré
            pass

@app.on_event("shutdown")
async def _on_shutdown():
    _stop.set()
    if _bg_task:
        try:
            await asyncio.wait_for(_bg_task, timeout=10)
        except asyncio.TimeoutError:
            pass
