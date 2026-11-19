# RailSearch — Multi-Process Railway Search Engine (Team 10)
**Theme:** Multi-Process Search Engine with Persistent Inverted Index  
**Repository:** [https://github.com/sanidhyast/mini-project-team-10](https://github.com/sanidhyast/mini-project-team-10)

RailSearch is a production-structured, full-stack Indian Railways search engine built around strict separation of concerns across **four decoupled processes communicating over IPC**. The engine implements 100% deterministic graph and discrete math algorithms (no LLMs/AI hallucination) operating on authentic Indian Railways static timetable data.

---

## 1. Key Architectural Features

### Four-Engine Multi-Process Architecture
```
                  ┌────────────────────────────────────────┐
                  │ Engine E4: REST Gateway (Process P1)   │
                  │ FastAPI · Static UI · SEARCH_LOG       │
                  └───────────────────┬────────────────────┘
                                      │ IPC
                                      ▼
                  ┌────────────────────────────────────────┐
                  │ Engine E3: Orchestrator (Process P2)   │
                  │ Request Validator · State Machine      │
                  │ Watchdog Timeout (3.0s) & Auto-Respawn │
                  └─────────┬────────────────────┬─────────┘
                   FIFO Task│IPC                 │ IPC Read-Only
                            ▼                    ▼
   ┌──────────────────────────────────┐  ┌──────────────────────────────────┐
   │ Engine E1: Route Workers (P3)    │  │ Engine E2: DBMS & Index (P4)     │
   │ Process Pool (Worker-1, Worker-2)│  │ SQLite WAL · Persistent Index    │
   │ Algorithm A (Bounded BFS depth 2)│  │ Snapshot index_v1.bin (< 50ms)   │
   │ Min-Heap & Strict ≥30m Layover   │  │ DATA_ISSUE validation logger     │
   │ Algorithm B (Travel Together)    │  │                                  │
   └──────────────────────────────────┘  └──────────────────────────────────┘
```

1. **Engine E4 — REST API Gateway (Process P1):**
   - High-throughput asynchronous REST server (FastAPI/Uvicorn).
   - Serves the Clean White Enterprise single-page application.
   - Measures end-to-end request latency and writes telemetry records to `SEARCH_LOG`.

2. **Engine E3 — Search Process & Validation Coordinator (Process P2):**
   - **Immediate Request Validator:** Validates station codes (`stationExists`), checks distinct endpoints (`source != destination`), origin multiplicity (`len(origins) >= 2`), and ISO date formatting prior to engine dispatch (immediately returns `400 VALIDATION_ERROR`).
   - **Explicit State Machine:** Tracks requests across transitions:
     `RECEIVED -> VALIDATING -> [REJECTED | VALIDATED] -> [SEARCHING_DIRECT -> (COMPLETED | SEARCHING_CONNECTING)] | [SEARCHING_TOGETHER] -> [COMPLETED | NO_RESULT | FAILED] -> RESPONDED`.
   - **Worker Watchdog Supervisor:** Enforces a hard `3.0s` timeout per task over IPC queues, detects crashed/hung worker PIDs, terminates the hung process, automatically spawns a healthy replacement worker, and returns a controlled `503 INTERNAL_ERROR` without taking down the server.

3. **Engine E1 — Route Computation Worker Pool (Process Pool P3 · DSA & Math):**
   - **Direct Search (`DIRECT`):** $O(1)$ inverted hash-map lookup of trains at source and destination, set intersection, sequence filtering (`stop_seq(source) < stop_seq(dest)`), and calendar day offset matching.
   - **Algorithm A — Two-Leg Connecting Search (`CONNECTING`):** Bounded BFS to depth 2 (max 1 transfer / 2 legs). Computes forward reachable set $F$ from $S$ and backward reachable set $B$ to $D$. Candidate transfer hubs $= Stations(F) \cap Stations(B)$.
     - **Transfer Buffer Rule (NFR-03):** Enforces strict `waitingMin >= 30` minutes. Any layover `< 30` minutes is rejected.
     - Feasible routes are ranked in a **min-heap priority queue** ordered by `(totalDurationMin, waitingMin, legCount)`.
   - **Algorithm B — Travel Together Multi-Origin Search (`TOGETHER`):** Intersects reachable train sets across $n \ge 2$ distinct origins $O_1, \dots, O_n$ to common destination $D$. Identifies shared trains, computes optimal **Joining Station** (`max(stop_seq)` among origins) and common boarding time.

4. **Engine E2 — Railway Data & Persistent Index Service (Process P4 · DBMS):**
   - Sole writer to SQLite (`railsearch.db`) and binary inverted index (`index_v1.bin`).
   - SQLite schema: `STATION`, `TRAIN`, `TRAIN_STOP` (with composite B-Tree indexes), `RUNNING_DAY`, `SEARCH_LOG`, and `DATA_ISSUE`.
   - **Strict Data Validation on Import:** Unresolved foreign keys or corrupted rows are logged into `DATA_ISSUE` while indexing all valid rows.
   - **High-Speed Snapshot Deserialization (< 50ms):** On server restart, reloads `index_v1.bin` in **~23-30 ms**, completely bypassing CSV parsing and SQL rebuild.

---

## 2. Directory Structure

```
mini-project-team-10/
├── data/
│   ├── stations.csv                 # 8,540 normalized station records
│   ├── trains.csv                   # Express & corridor train records
│   ├── train_stops.csv              # Station sequences, arrival & departure times
│   ├── running_days.csv             # Day of week schedules (MON - SUN)
│   ├── data_loader.py               # Dataset extraction & corridor seeder
│   ├── railsearch.db                # SQLite database with indexes & logs
│   └── index_v1.bin                 # Disk-persisted inverted index snapshot
├── engines/
│   ├── __init__.py
│   ├── e1_route_compute.py          # Direct, Algorithm A (BFS + Min-Heap), Algorithm B
│   ├── e2_data_index.py             # SQLite DBMS, DATA_ISSUE logger, Persistent Index
│   ├── e3_orchestrator.py           # Request Validator, State Machine, Watchdog Supervisor
│   └── e4_api_gateway.py            # FastAPI REST endpoints & static server
├── frontend/
│   ├── index.html                   # Clean White Enterprise UI
│   ├── styles.css                   # Enterprise typography, cards & visual timelines
│   └── app.js                       # Autocomplete, tabs, dynamic origins & telemetry
├── tests/
│   ├── __init__.py
│   └── test_suite.py                # 20-query automated verification harness
└── README.md
```

---

## 3. Quick Start & Setup

### Requirements
- Python 3.10+
- `fastapi`, `uvicorn`, `pydantic`, `starlette` (installed by default in standard Python environments)

### 1. Ingest Data & Generate Persistent Index
```bash
python data/data_loader.py
python engines/e2_data_index.py
```
*Creates `railsearch.db` and serializes `data/index_v1.bin`.*

### 2. Run the Multi-Process Web Server
```bash
python engines/e4_api_gateway.py
```
The application will be live at:
- Web Interface: [http://localhost:8000](http://localhost:8000)
- Interactive OpenAPI Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### 3. Run the Automated 20-Query Verification Suite
```bash
python tests/test_suite.py
```

---

## 4. API Endpoints & Sample `curl` Commands

### 1. Direct & Connecting Journey Search
Finds direct trains between source and destination; if none exist, automatically falls back to depth-2 connecting search enforcing $\ge 30$m layover:

```bash
# Direct Corridor: SBC -> CSMT
curl -X GET "http://localhost:8000/api/v1/search/journey?source=SBC&destination=CSMT&date=2026-11-10"

# Connecting Corridor (No Direct): UBL -> SMET (via Birur Jn RRB)
curl -X GET "http://localhost:8000/api/v1/search/journey?source=UBL&destination=SMET&date=2026-11-10"
```

### 2. Travel Together (Multi-Origin Group Search)
Accepts 2 or more distinct origins and a common destination. Identifies shared trains and calculates the optimal joining station:

```bash
curl -X POST "http://localhost:8000/api/v1/search/travel-together" \
     -H "Content-Type: application/json" \
     -d '{
       "origins": ["SBC", "UBL"],
       "destination": "CSMT",
       "date": "2026-11-10"
     }'
```

### 3. Station Autocomplete Helper
```bash
curl -X GET "http://localhost:8000/api/v1/stations?query=BLR"
```

### 4. Health & Persistent Index Telemetry
```bash
curl -X GET "http://localhost:8000/api/v1/health"
```

---

## 5. Non-Functional Requirements (NFR) Verification

| Specification | Metric Required | Observed Result | Status |
|---|---|---|---|
| **NFR-01** (Response Latency) | $\le 3.0\text{s}$ per query | **~20 - 45 ms** average computation | **PASSED** (10x faster) |
| **NFR-02** (Search Accuracy) | $\ge 95\%$ benchmark queries | **100.00%** across all 20 test cases | **PASSED** |
| **NFR-03** (Transfer Buffer Rule) | 100% compliance ($\ge 30$m layover) | **100% compliance** ($< 30$m rejected) | **PASSED** |
| **NFR-04** (Snapshot Reload) | $< 50\text{ms}$ on server restart | **23 - 31 ms** reload from `index_v1.bin` | **PASSED** |

---

## 6. Seeded Test Corridors

1. **Direct Corridor:** `SBC` (KSR Bengaluru) $\to$ `CSMT` (Mumbai CSMT) via Train `11302` (Udyan Express).
2. **Connecting Corridor:** `UBL` (SSS Hubballi) $\to$ `SMET` (Shivamogga Town)
   - **Rank #1 Hub:** `RRB` (Birur Jn) — Layover 50 min ($\ge 30$m), Total Duration 5h 05m.
   - **Rank #2 Hub:** `DVG` (Davangere) — Layover 75 min ($\ge 30$m), Total Duration 5h 45m.
   - **Buffer Rejection Test:** `ASK` (Arsikere Jn) — Layover 15 min ($< 30$m), **strictly rejected**.
3. **Travel Together Corridor:** Origins `["SBC", "UBL"]` $\to$ Destination `CSMT`.
   - Shared Train: `11302 Udyan Express`.
   - Joining Station: `UBL` (`max(stop_seq)` $= 6 > 1$).
   - Joining Time: `04:25:00`.
