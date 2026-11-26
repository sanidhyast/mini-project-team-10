"""
Engine E4 — Query & Result Interface Gateway (Process P1 · Web, Security & Networks)

FastAPI REST API server providing:
1. Journey Search REST API:
   - GET /api/v1/search/journey
   - TRACEABILITY: [FR-01], [FR-02], [FR-03], [FR-04], [NFR-01] (<= 3.0s latency), [NFR-04] (HTTP 400 validation).
2. Travel Together Coordinated Search REST API:
   - POST /api/v1/search/travel-together
   - TRACEABILITY: [FR-10], [FR-11], [FR-12], [NFR-01], [NFR-04].
3. User Authentication & Verification REST APIs:
   - POST /api/v1/auth/register-init (Generate OTP & dispatch email)
   - POST /api/v1/auth/verify-otp (Verify 6-digit OTP token)
   - POST /api/v1/auth/complete-registration (Salted hash password creation)
   - POST /api/v1/auth/login (Credential authentication)
4. Admin Timetable CRUD & Hot Snapshot Rebuild:
   - GET/POST /api/v1/admin/trains
   - GET/PUT/DELETE /api/v1/admin/trains/{train_no}
   - POST /api/v1/admin/rebuild-index [NFR-04 Supplemental]
5. Static SPA UI Server:
   - Serves authentic Indian Railways responsive frontend with search gating.
6. Telemetry & SEARCH_LOG persistence:
   - Measures end-to-end response times and logs audit records to SQLite SEARCH_LOG table.
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

class RegisterInitRequest(BaseModel):
    full_name: str = Field(..., example="Rahul Sharma")
    mobile: str = Field(..., example="9876543210")
    email: str = Field(..., example="rahul@example.com")
    dob: str = Field(..., example="1998-05-12")
    gender: str = Field(..., example="Male")

class VerifyOtpRequest(BaseModel):
    email: str
    otp: str

class CompleteRegistrationRequest(BaseModel):
    email: str
    password: str
    confirm_password: str

class LoginRequest(BaseModel):
    identifier: str = Field(..., example="admin")
    password: str = Field(..., example="admin123")

class SmtpConfigRequest(BaseModel):
    smtp_user: str
    smtp_password: str
    smtp_host: Optional[str] = "smtp.gmail.com"
    smtp_port: Optional[int] = 587

class TrainStopItem(BaseModel):
    station_code: str
    stop_seq: int
    arrival_time: str
    departure_time: str
    day_no: Optional[int] = 1
    distance_km: Optional[float] = 0.0

class TrainSaveRequest(BaseModel):
    train_no: str
    train_name: str
    running_days: List[str]
    stops: List[TrainStopItem]

# Services
def get_gateway_index_service():
    return get_data_index_service()

def get_gateway_orchestrator():
    return get_orchestrator()

# ==============================================================================
# REST API ENDPOINTS & SEARCH TELEMETRY [FR-01, FR-10, NFR-01, NFR-04]
# ==============================================================================

@app.get("/api/v1/search/journey")
async def search_journey_api(
    source: Optional[str] = Query(None, description="Origin station code"),
    destination: Optional[str] = Query(None, description="Destination station code"),
    date: Optional[str] = Query(None, description="Journey date YYYY-MM-DD"),
    simulate_timeout: bool = Query(False, description="Simulate worker timeout for resilience test")
):
    """
    [FR-01, FR-02, FR-03, FR-04, NFR-01, NFR-04]
    Direct & Connecting journey search. Dispatches to Engine E3 via Python interface.
    Measures end-to-end latency and persists audit records to SQLite SEARCH_LOG table.
    """
    t_start = time.perf_counter()
    params_str = json.dumps({"source": source, "destination": destination, "date": date})

    orchestrator = get_gateway_orchestrator()
    if orchestrator is None:
        return JSONResponse(status_code=503, content={"status": "ERROR", "message": "Orchestrator not initialized in main process"})

    res = orchestrator.execute_journey_search(source, destination, date, simulate_timeout=simulate_timeout)
    elapsed_ms = (time.perf_counter() - t_start) * 1000.0
    status_code = res.get("status_code", 200)

    # Persist to SEARCH_LOG table [NFR-01, NFR-02 telemetry]
    get_gateway_index_service().log_search("JOURNEY", params_str, status_code, elapsed_ms)

    res["response_time_ms"] = round(elapsed_ms, 2)
    return JSONResponse(status_code=status_code, content=res)

@app.post("/api/v1/search/travel-together")
async def search_travel_together_api(payload: TravelTogetherRequest):
    """
    [FR-10, FR-11, FR-12, NFR-01, NFR-04]
    Travel Together multi-origin coordinated search. Dispatches to Engine E3.
    """
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

    # Persist to SEARCH_LOG table [NFR-01, NFR-02 telemetry]
    get_gateway_index_service().log_search("TRAVEL_TOGETHER", params_str, status_code, elapsed_ms)

    res["response_time_ms"] = round(elapsed_ms, 2)
    return JSONResponse(status_code=status_code, content=res)

@app.get("/api/v1/search/graph-analysis")
async def graph_analysis_api(
    source: str = Query(..., description="Origin station code"),
    destination: str = Query(..., description="Destination station code"),
    date: str = Query("2026-11-10", description="Date YYYY-MM-DD")
):
    """
    [Graph Algorithms Evaluation]
    Evaluates connecting route options across Dijkstra, BFS, and DFS graph engines:
    - Dijkstra: Shortest physical track distance (km)
    - BFS: Minimal transfer hops level-by-level
    - DFS: Viable alternative routing corridor exploration
    """
    from engines.e1_route_compute import dijkstra_shortest_path, bfs_shortest_transfers, dfs_find_all_paths
    idx = get_gateway_index_service()

    dijkstra_res = dijkstra_shortest_path(source, destination, date, idx)
    bfs_res = bfs_shortest_transfers(source, destination, date, idx)
    dfs_res = dfs_find_all_paths(source, destination, date, idx, max_depth=2)

    return {
        "status": "SUCCESS",
        "source": source.upper(),
        "destination": destination.upper(),
        "dijkstra_shortest_path": dijkstra_res,
        "bfs_minimum_transfers": bfs_res,
        "dfs_corridors_count": len(dfs_res),
        "dfs_corridors_sample": dfs_res[:5]
    }

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

# ================= Authentication Endpoints =================

@app.post("/api/v1/auth/register-init")
async def register_init_api(payload: RegisterInitRequest):
    svc = get_gateway_index_service()
    ok, otp, warn = svc.create_registration_otp(
        payload.full_name, payload.mobile, payload.email, payload.dob, payload.gender
    )
    if not ok:
        return JSONResponse(status_code=400, content={"status": "ERROR", "message": warn or "Failed to initiate registration."})

    from engines.email_service import get_smtp_config
    smtp_cfg = get_smtp_config()
    is_smtp_set = bool(smtp_cfg.get("smtp_user") and smtp_cfg.get("smtp_password"))

    resp = {
        "status": "SUCCESS",
        "message": f"Verification code sent to {payload.email}.",
        "email": payload.email.lower().strip(),
        "smtp_configured": is_smtp_set
    }
    # If in local testing or warning present, include test OTP hint
    if not is_smtp_set or warn:
        resp["simulated_otp"] = otp
        resp["hint"] = "SMTP not yet configured or in simulation mode. Use the displayed code to verify, or configure Gmail App Password in Admin."

    return JSONResponse(status_code=200, content=resp)

@app.post("/api/v1/auth/verify-otp")
async def verify_otp_api(payload: VerifyOtpRequest):
    svc = get_gateway_index_service()
    ok, err_msg = svc.verify_registration_otp(payload.email, payload.otp)
    if not ok:
        return JSONResponse(status_code=400, content={"status": "ERROR", "message": err_msg})
    return JSONResponse(status_code=200, content={"status": "SUCCESS", "message": "Email verified successfully. You may now create your password."})

@app.post("/api/v1/auth/complete-registration")
async def complete_registration_api(payload: CompleteRegistrationRequest):
    svc = get_gateway_index_service()
    ok, user, err_msg = svc.complete_registration(payload.email, payload.password, payload.confirm_password)
    if not ok:
        return JSONResponse(status_code=400, content={"status": "ERROR", "message": err_msg})
    return JSONResponse(status_code=201, content={
        "status": "SUCCESS",
        "message": "Account created successfully. Please log in with your credentials.",
        "user": user
    })

@app.post("/api/v1/auth/login")
async def login_api(payload: LoginRequest):
    svc = get_gateway_index_service()
    user = svc.authenticate(payload.identifier, payload.password)
    if not user:
        return JSONResponse(status_code=401, content={"status": "ERROR", "message": "Invalid email/username or password."})

    # Simple session token for the user/admin
    token = f"token_{user['user_id']}_{int(time.time())}"
    return JSONResponse(status_code=200, content={
        "status": "SUCCESS",
        "message": "Login successful.",
        "token": token,
        "user": user
    })

# ================= Admin Timetable Endpoints =================

@app.get("/api/v1/admin/trains")
async def admin_list_trains_api(
    search: Optional[str] = Query("", description="Train number or name substring"),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100)
):
    svc = get_gateway_index_service()
    return svc.admin_list_trains(search=search or "", page=page, limit=limit)

@app.get("/api/v1/admin/trains/{train_no}")
async def admin_get_train_api(train_no: str):
    svc = get_gateway_index_service()
    train = svc.admin_get_train(train_no)
    if not train:
        raise HTTPException(status_code=404, detail=f"Train {train_no} not found.")
    return train

@app.post("/api/v1/admin/trains")
async def admin_create_train_api(payload: TrainSaveRequest):
    svc = get_gateway_index_service()
    try:
        stops_list = [s.model_dump() for s in payload.stops]
        res = svc.admin_save_train(payload.train_no, payload.train_name, payload.running_days, stops_list)
        return JSONResponse(status_code=201, content=res)
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "ERROR", "message": str(e)})

@app.put("/api/v1/admin/trains/{train_no}")
async def admin_update_train_api(train_no: str, payload: TrainSaveRequest):
    svc = get_gateway_index_service()
    try:
        stops_list = [s.model_dump() for s in payload.stops]
        res = svc.admin_save_train(train_no, payload.train_name, payload.running_days, stops_list)
        return JSONResponse(status_code=200, content=res)
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "ERROR", "message": str(e)})

@app.delete("/api/v1/admin/trains/{train_no}")
async def admin_delete_train_api(train_no: str):
    svc = get_gateway_index_service()
    ok = svc.admin_delete_train(train_no)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Failed to delete train {train_no}.")
    return {"status": "SUCCESS", "message": f"Train {train_no} deleted successfully."}

@app.post("/api/v1/admin/rebuild-index")
async def admin_rebuild_index_api():
    t0 = time.perf_counter()
    svc = get_gateway_index_service()
    reload_ms = svc.rebuild_index_hot()
    elapsed_total = (time.perf_counter() - t0) * 1000.0
    return {
        "status": "SUCCESS",
        "message": f"Persistent index rebuilt and reloaded in memory.",
        "reload_ms": round(reload_ms, 2),
        "total_elapsed_ms": round(elapsed_total, 2)
    }

@app.get("/api/v1/admin/smtp-config")
async def get_smtp_config_api():
    from engines.email_service import get_smtp_config
    cfg = get_smtp_config()
    # Mask password for security
    masked_pass = "********" if cfg.get("smtp_password") else ""
    return {
        "smtp_host": cfg.get("smtp_host", "smtp.gmail.com"),
        "smtp_port": cfg.get("smtp_port", 587),
        "smtp_user": cfg.get("smtp_user", ""),
        "has_password": bool(cfg.get("smtp_password")),
        "smtp_password": masked_pass
    }

@app.post("/api/v1/admin/smtp-config")
async def save_smtp_config_api(payload: SmtpConfigRequest):
    from engines.email_service import save_smtp_config
    res = save_smtp_config(
        payload.smtp_user,
        payload.smtp_password,
        payload.smtp_host or "smtp.gmail.com",
        payload.smtp_port or 587
    )
    return res

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
