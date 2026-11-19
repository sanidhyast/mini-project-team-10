"""
Engine E4 — Query & Result Interface Gateway (Process P1 · Web & Networks)
FastAPI REST server providing:
- GET /api/v1/search/journey
- POST /api/v1/search/travel-together
- GET /api/v1/stations
- GET /api/v1/health
- Static frontend server for index.html, styles.css, app.js
- Telemetry & SEARCH_LOG persistence
"""

import os
import sys
import time
import json
import logging
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Request, Query, HTTPException, Response
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure mini-project-team-10 is on path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from engines.e2_data_index import get_data_index_service
from engines.e3_orchestrator import get_orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [E4-GATEWAY] %(message)s")

app = FastAPI(
    title="RailSearch Engine — Team 10",
    description="Multi-Process Railway Search Engine with Persistent Inverted Index",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

# Pydantic schemas
class TravelTogetherRequest(BaseModel):
    origins: List[str] = Field(..., example=["SBC", "UBL"])
    destination: str = Field(..., example="CSMT")
    date: str = Field(..., example="2026-11-10")
    simulate_timeout: Optional[bool] = False

# Services
def get_gateway_index_service():
    return get_data_index_service()

def get_gateway_orchestrator():
    return get_orchestrator()

@app.get("/api/v1/search/journey")
async def search_journey_api(
    source: Optional[str] = Query(None, description="Origin station code"),
    destination: Optional[str] = Query(None, description="Destination station code"),
    date: Optional[str] = Query(None, description="Journey date YYYY-MM-DD"),
    simulate_timeout: bool = Query(False, description="Simulate worker timeout for resilience test")
):
    t_start = time.perf_counter()
    params_str = json.dumps({"source": source, "destination": destination, "date": date})

    orchestrator = get_gateway_orchestrator()
    if orchestrator is None:
        return JSONResponse(status_code=503, content={"status": "ERROR", "message": "Orchestrator not initialized in main process"})

    res = orchestrator.execute_journey_search(source, destination, date, simulate_timeout=simulate_timeout)
    elapsed_ms = (time.perf_counter() - t_start) * 1000.0
    status_code = res.get("status_code", 200)

    # Persist to SEARCH_LOG table
    get_gateway_index_service().log_search("JOURNEY", params_str, status_code, elapsed_ms)

    res["response_time_ms"] = round(elapsed_ms, 2)
    return JSONResponse(status_code=status_code, content=res)

@app.post("/api/v1/search/travel-together")
async def search_travel_together_api(payload: TravelTogetherRequest):
    t_start = time.perf_counter()
    params_str = json.dumps({
        "origins": payload.origins,
        "destination": payload.destination,
        "date": payload.date
    })

    orchestrator = get_gateway_orchestrator()
    if orchestrator is None:
        return JSONResponse(status_code=503, content={"status": "ERROR", "message": "Orchestrator not initialized in main process"})

    res = orchestrator.execute_travel_together_search(
        payload.origins,
        payload.destination,
        payload.date,
        simulate_timeout=payload.simulate_timeout
    )
    elapsed_ms = (time.perf_counter() - t_start) * 1000.0
    status_code = res.get("status_code", 200)

    # Persist to SEARCH_LOG table
    get_gateway_index_service().log_search("TRAVEL_TOGETHER", params_str, status_code, elapsed_ms)

    res["response_time_ms"] = round(elapsed_ms, 2)
    return JSONResponse(status_code=status_code, content=res)

@app.get("/api/v1/stations")
async def get_stations_api(query: Optional[str] = Query(None, description="Filter prefix or substring")):
    all_stations = get_gateway_index_service().getAllStations()
    if not query or not query.strip():
        popular = ["SBC", "UBL", "RRB", "SMET", "DVG", "ASK", "CSMT", "NDLS", "HWH", "MAS", "PUNE"]
        res = [s for s in all_stations if s["station_code"] in popular]
        return res

    q = query.strip().upper()
    matches = []
    for s in all_stations:
        code = s.get("station_code", "")
        name = s.get("station_name", "").upper()
        city = s.get("city", "").upper()
        if code.startswith(q) or q in name or q in city:
            matches.append(s)
            if len(matches) >= 50:
                break
    return matches

@app.get("/api/v1/health")
async def health_check_api():
    stats = get_gateway_index_service().getStats()
    orchestrator = get_gateway_orchestrator()
    worker_pids = {f"worker_{wid}": p.pid for wid, p in orchestrator.workers.items()} if orchestrator else {}
    return {
        "status": "HEALTHY",
        "timestamp": time.time(),
        "gateway_pid": os.getpid(),
        "worker_pids": worker_pids,
        "database_and_index": stats
    }

# Mount static frontend
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
async def serve_frontend():
    index_html = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_html):
        return FileResponse(index_html)
    return {"message": "RailSearch API Gateway Running. Visit /docs for API documentation."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("engines.e4_api_gateway:app", host="0.0.0.0", port=8000, reload=False)
