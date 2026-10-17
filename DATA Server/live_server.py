"""
live_server.py
══════════════
FastAPI server that:
  1. Receives sensor data from the Arduino  POST /ingest
  2. Pushes real-time updates to the browser via SSE  GET /stream
  3. Serves the latest sensor snapshot as JSON  GET /data/latest
  4. Serves recent history as JSON  GET /data/history?minutes=60
  5. Serves the buzzer status for the Arduino  GET /buzzer_status
  6. Serves live_dashboard.html as the root  GET /

Run:
    uvicorn live_server:app --host 0.0.0.0 --port 8502 --reload

Then open:  http://localhost:8502
"""

import asyncio
import csv
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import AsyncGenerator

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── Config ────────────────────────────────────────────────────────────────────
DATA_FILE   = Path("sensor_data.csv")
BUZZER_FLAG = Path("buzzer_alert.txt")
HTML_FILE   = Path("live_dashboard.html")   # served at GET /

# CSV column order expected from Arduino POST /ingest
CSV_COLUMNS = ["timestamp", "ultrasonic_cm", "water_level_pct", "flow_lpm", "turb_ntu"]

# In-memory broadcast queue: all active SSE clients subscribe here
_subscribers: list[asyncio.Queue] = []

app = FastAPI(title="TSF Live Server")

# Let the 3D digital twin (booth/index.html on another port) read data — GET only
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

# ── Helper: append row to CSV ─────────────────────────────────────────────────
def _append_csv(row: dict):
    write_header = not DATA_FILE.exists() or DATA_FILE.stat().st_size == 0
    with open(DATA_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        # Ensure timestamp is present
        if "timestamp" not in row:
            row["timestamp"] = datetime.now(timezone.utc).isoformat()
        writer.writerow(row)


# ── Helper: broadcast SSE event to all subscribers ───────────────────────────
def _broadcast(payload: dict):
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.remove(q)


# ── POST /ingest — Arduino sends data here ───────────────────────────────────
@app.post("/ingest")
async def ingest(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # Add server-side UTC timestamp
    body["timestamp"] = datetime.now(timezone.utc).isoformat()

    # Persist to CSV
    _append_csv(body)

    # Broadcast to all SSE clients immediately
    _broadcast(body)

    return JSONResponse({"status": "ok"})


# ── GET /stream — SSE endpoint; browser connects here ────────────────────────
@app.get("/stream")
async def stream(request: Request):
    """
    Server-Sent Events endpoint.
    The browser connects once with EventSource('/stream') and receives
    a push event every time the Arduino sends new data to /ingest.
    No polling, no page reload.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.append(q)

    async def event_generator() -> AsyncGenerator[str, None]:
        # Send a heartbeat immediately so the browser knows the connection is live
        yield "event: heartbeat\ndata: connected\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"event: sensor\ndata: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive ping every 15 s to prevent proxy timeout
                    yield "event: ping\ndata: keep-alive\n\n"
        finally:
            if q in _subscribers:
                _subscribers.remove(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


# ── GET /data/latest — returns the most recent sensor row as JSON ─────────────
@app.get("/data/latest")
def data_latest():
    if not DATA_FILE.exists():
        return JSONResponse({"error": "No data yet"}, status_code=404)
    df = pd.read_csv(DATA_FILE)
    if df.empty:
        return JSONResponse({"error": "Empty CSV"}, status_code=404)
    row = df.iloc[-1].to_dict()
    return JSONResponse(row)


# ── GET /data/history — returns last N minutes as JSON array ──────────────────
@app.get("/data/history")
def data_history(minutes: int = 60):
    if not DATA_FILE.exists():
        return JSONResponse([], status_code=200)
    df = pd.read_csv(DATA_FILE)
    if df.empty:
        return JSONResponse([], status_code=200)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    cutoff = df["timestamp"].max() - timedelta(minutes=minutes)
    recent = df[df["timestamp"] >= cutoff].copy()
    recent["timestamp"] = recent["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return JSONResponse(recent.to_dict(orient="records"))


# ── GET /buzzer_status — Arduino polls this ───────────────────────────────────
@app.get("/buzzer_status")
def buzzer_status():
    try:
        val = BUZZER_FLAG.read_text().strip()
        state = 1 if val == "1" else 0
    except FileNotFoundError:
        state = 0
    return JSONResponse({"buzzer": state})


# ── GET / — serve the live dashboard HTML ────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    if HTML_FILE.exists():
        return HTMLResponse(HTML_FILE.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>live_dashboard.html not found</h1>", status_code=404)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    subscribers = len(_subscribers)
    rows = sum(1 for _ in open(DATA_FILE)) - 1 if DATA_FILE.exists() else 0
    return JSONResponse({"status": "ok", "sse_clients": subscribers, "csv_rows": rows})