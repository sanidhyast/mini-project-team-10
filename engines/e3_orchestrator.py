"""
Engine E3 — Coordinator & Supervisor Service (Process P2 · State Machine & Fault Tolerance)

This module manages request lifecycles, IPC dispatch, and worker supervision:
1. Deterministic Request State Machine:
   - Tracks explicit state transitions:
     RECEIVED -> VALIDATING -> [REJECTED | VALIDATED] ->
     [SEARCHING_DIRECT -> (COMPLETED | SEARCHING_CONNECTING)] | [SEARCHING_TOGETHER] ->
     [COMPLETED | NO_RESULT | FAILED] -> RESPONDED.
2. Immediate Pre-Dispatch Request Validator:
   - TRACEABILITY: [FR-01], [FR-10], [NFR-04] (Returns HTTP 400 without crashing or touching worker pool).
   - Validates station codes against in-memory index (stationExists).
   - Validates distinct source/destination and distinct origins (len(origins) >= 2).
   - Validates ISO date formats (YYYY-MM-DD).
3. Worker Watchdog Supervisor:
   - TRACEABILITY: [NFR-01] Enforces 3.0-second performance ceiling over IPC queues.
   - Detects hung or crashed worker processes, terminates rogue PIDs, and respawns a healthy pool.
   - Returns controlled HTTP 503 without degrading overall system stability.
"""

import os
import sys
import time
import uuid
import logging
import multiprocessing as mp
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [E3-ORCHESTRATOR] %(message)s")

class RequestStateMachine:
    """Explicit deterministic state machine tracking search request transitions."""
    def __init__(self, request_id: str, request_type: str):
        self.request_id = request_id
        self.request_type = request_type
        self.history: List[Tuple[str, float]] = []
        self.current_state = "RECEIVED"
        self.transition("RECEIVED")

    def transition(self, new_state: str):
        self.current_state = new_state
        self.history.append((new_state, time.perf_counter()))
        logging.debug(f"[StateReq {self.request_id}] -> {new_state}")

    def get_summary(self) -> Dict[str, Any]:
        return {
            "current_state": self.current_state,
            "states_traversed": [s[0] for s in self.history],
            "total_states": len(self.history)
        }

class SearchOrchestrator:
    """
    Supervisor orchestrator managing IPC task dispatch, pre-validation,
    and watchdog timeout enforcement [NFR-01, NFR-04].
    """
    def __init__(self, num_workers: int = 2, timeout_sec: float = 3.0):
        self.num_workers = num_workers
        self.timeout_sec = timeout_sec

        self.task_queue: Optional[mp.Queue] = None
        self.response_queue: Optional[mp.Queue] = None
        self.workers: Dict[int, mp.Process] = {} # worker_id -> Process

        from engines.e2_data_index import get_data_index_service
        self.index_service = get_data_index_service()

        self._start_worker_pool()

    def _start_worker_pool(self):
        """Initializes FIFO IPC queues and spawns worker processes."""
        self.task_queue = mp.Queue()
        self.response_queue = mp.Queue()

        from engines.e1_route_compute import worker_process_main

        for i in range(self.num_workers):
            p = mp.Process(
                target=worker_process_main,
                args=(self.task_queue, self.response_queue, i + 1),
                daemon=True
            )
            p.start()
            self.workers[i + 1] = p
            logging.info(f"Spawned E1 Worker-{i + 1} with PID {p.pid}")

    def _respawn_all_workers(self):
        """Kills all hung workers, recreates IPC queues to prevent pipe deadlock, and spawns fresh workers."""
        for w_id, proc in list(self.workers.items()):
            try:
                if proc.is_alive():
                    logging.warning(f"Terminating hung Worker-{w_id} (PID {proc.pid})...")
                    proc.terminate()
                    proc.join(timeout=0.2)
                    if proc.is_alive():
                        proc.kill()
            except Exception as e:
                logging.error(f"Error terminating worker {w_id}: {e}")
        
        self.workers.clear()
        self._start_worker_pool()
        logging.info("Supervisor successfully respawned clean worker pool with fresh IPC queues.")

    # ==========================================================================
    # PRE-DISPATCH VALIDATION [FR-01, FR-10, NFR-04]
    # ==========================================================================
    # Fast-fail validation: Invalid inputs return HTTP 400 immediately,
    # preventing malformed queries from entering the IPC queues or worker pool.
    # ==========================================================================

    def validate_journey_request(self, source: Optional[str], destination: Optional[str], date_str: Optional[str]) -> Tuple[bool, Optional[str]]:
        """
        [FR-01, NFR-04] Strict validation of journey search parameters:
        - Presence of source, destination, date
        - Source != Destination
        - Valid ISO YYYY-MM-DD date format
        - Valid station existence in index
        """
        if not source or not str(source).strip():
            return False, "Source station code is required."
        if not destination or not str(destination).strip():
            return False, "Destination station code is required."

        src = str(source).strip().upper()
        dst = str(destination).strip().upper()

        if src == dst:
            return False, f"Source and destination stations must be distinct. Got identical code '{src}'."

        if not date_str or not str(date_str).strip():
            return False, "Journey date is required (YYYY-MM-DD)."
        try:
            datetime.fromisoformat(str(date_str).strip())
        except ValueError:
            return False, f"Invalid date format '{date_str}'. Expected ISO format YYYY-MM-DD."

        if not self.index_service.stationExists(src):
            return False, f"Unknown station code '{src}'."
        if not self.index_service.stationExists(dst):
            return False, f"Unknown station code '{dst}'."

        return True, None

    def validate_travel_together_request(self, origins: Any, destination: Optional[str], date_str: Optional[str]) -> Tuple[bool, Optional[str]]:
        """
        [FR-10, NFR-04] Strict validation of travel together parameters:
        - len(origins) >= 2
        - All origin station codes unique
        - Destination not among origins
        - Valid ISO date format & stations exist in index
        """
        if not origins or not isinstance(origins, list):
            return False, "Origins must be a list containing at least 2 distinct station codes."
        if len(origins) < 2:
            return False, f"At least 2 distinct origins are required. Got {len(origins)}."

        clean_origins = [str(o).strip().upper() for o in origins]
        if len(set(clean_origins)) != len(clean_origins):
            return False, f"Duplicate origin stations are not allowed: {origins}"

        if not destination or not str(destination).strip():
            return False, "Destination station code is required."
        dst = str(destination).strip().upper()

        if dst in clean_origins:
            return False, f"Destination station '{dst}' cannot be among origin stations."

        if not date_str or not str(date_str).strip():
            return False, "Journey date is required (YYYY-MM-DD)."
        try:
            datetime.fromisoformat(str(date_str).strip())
        except ValueError:
            return False, f"Invalid date format '{date_str}'. Expected ISO format YYYY-MM-DD."

        for origin in clean_origins:
            if not self.index_service.stationExists(origin):
                return False, f"Unknown origin station code '{origin}'."
        if not self.index_service.stationExists(dst):
            return False, f"Unknown destination station code '{dst}'."

        return True, None

    # ==========================================================================
    # WORKER DISPATCH & SUPERVISOR WATCHDOG [NFR-01, FR-04]
    # ==========================================================================

    def execute_journey_search(self, source: str, destination: str, date_str: str, simulate_timeout: bool = False) -> Dict[str, Any]:
        """
        Coordinates journey search with state machine tracking and watchdog timeout supervisor.
        - [FR-01] Accepts source, destination, date.
        - [FR-04] Automatic connecting journey search if direct yields 0 results.
        - [NFR-01] Enforces 3.0-second timeout ceiling; auto-respawns workers on hang.
        """
        req_id = str(uuid.uuid4())
        sm = RequestStateMachine(req_id, "JOURNEY")
        sm.transition("VALIDATING")

        is_valid, err_msg = self.validate_journey_request(source, destination, date_str)
        if not is_valid:
            sm.transition("REJECTED")
            sm.transition("RESPONDED")
            return {
                "status_code": 400,
                "status": "VALIDATION_ERROR",
                "message": err_msg,
                "state_machine": sm.get_summary()
            }

        sm.transition("VALIDATED")
        sm.transition("SEARCHING_DIRECT")

        task_payload = {
            "task_id": req_id,
            "task_type": "JOURNEY",
            "params": {
                "source": source.strip().upper(),
                "destination": destination.strip().upper(),
                "date": date_str.strip(),
                "simulate_timeout": simulate_timeout,
                "simulate_timeout_sec": 4.0 if simulate_timeout else 0.0
            }
        }

        # Dispatch via FIFO queue
        self.task_queue.put(task_payload)

        # Worker Watchdog Supervisor: Enforces 3.0s timeout
        t_start = time.perf_counter()
        response = None
        import queue

        while (time.perf_counter() - t_start) < self.timeout_sec:
            remaining = self.timeout_sec - (time.perf_counter() - t_start)
            if remaining <= 0:
                break
            try:
                resp = self.response_queue.get(timeout=min(0.1, remaining))
                if resp.get("task_id") == req_id:
                    response = resp
                    break
                else:
                    # Stale response from previous timed-out task: safely drop
                    logging.info(f"Dropped stale response from previous task {resp.get('task_id')}")
            except queue.Empty:
                continue
            except Exception as e:
                logging.debug(f"Queue get exception: {e}")
                time.sleep(0.01)

        # Timeout Watchdog Triggered
        if response is None:
            sm.transition("FAILED")
            sm.transition("RESPONDED")
            logging.error(f"[Watchdog] Task {req_id} timed out after {self.timeout_sec}s! Respawning hung worker pool...")
            self._respawn_all_workers()
            return {
                "status_code": 503,
                "status": "INTERNAL_ERROR",
                "message": f"Search worker timed out (> {self.timeout_sec}s) or hung. Worker process respawned by Watchdog supervisor.",
                "state_machine": sm.get_summary()
            }

        # Check response status and mode
        mode = response.get("mode", "DIRECT")
        if mode == "CONNECTING":
            sm.transition("SEARCHING_CONNECTING")

        if response.get("status") == "SUCCESS":
            sm.transition("COMPLETED")
        elif response.get("status") == "NO_ROUTE":
            sm.transition("NO_RESULT")
        else:
            sm.transition("FAILED")

        sm.transition("RESPONDED")

        return {
            "status_code": 200,
            "status": response.get("status"),
            "mode": mode,
            "data": response.get("data", []),
            "worker_pid": response.get("worker_pid"),
            "computation_ms": response.get("elapsed_ms", 0.0),
            "state_machine": sm.get_summary()
        }

    def execute_travel_together_search(self, origins: List[str], destination: str, date_str: str, simulate_timeout: bool = False) -> Dict[str, Any]:
        """
        Coordinates travel together search with state machine tracking and watchdog timeout supervisor.
        """
        req_id = str(uuid.uuid4())
        sm = RequestStateMachine(req_id, "TRAVEL_TOGETHER")
        sm.transition("VALIDATING")

        is_valid, err_msg = self.validate_travel_together_request(origins, destination, date_str)
        if not is_valid:
            sm.transition("REJECTED")
            sm.transition("RESPONDED")
            return {
                "status_code": 400,
                "status": "VALIDATION_ERROR",
                "message": err_msg,
                "state_machine": sm.get_summary()
            }

        sm.transition("VALIDATED")
        sm.transition("SEARCHING_TOGETHER")

        clean_origins = [o.strip().upper() for o in origins]
        dst = destination.strip().upper()

        task_payload = {
            "task_id": req_id,
            "task_type": "TOGETHER",
            "params": {
                "origins": clean_origins,
                "destination": dst,
                "date": date_str.strip(),
                "simulate_timeout": simulate_timeout,
                "simulate_timeout_sec": 4.0 if simulate_timeout else 0.0
            }
        }

        self.task_queue.put(task_payload)

        # Watchdog timeout loop
        t_start = time.perf_counter()
        response = None
        import queue

        while (time.perf_counter() - t_start) < self.timeout_sec:
            remaining = self.timeout_sec - (time.perf_counter() - t_start)
            if remaining <= 0:
                break
            try:
                resp = self.response_queue.get(timeout=min(0.1, remaining))
                if resp.get("task_id") == req_id:
                    response = resp
                    break
                else:
                    logging.info(f"Dropped stale response from previous task {resp.get('task_id')}")
            except queue.Empty:
                continue
            except Exception as e:
                logging.debug(f"Queue get exception: {e}")
                time.sleep(0.01)

        if response is None:
            sm.transition("FAILED")
            sm.transition("RESPONDED")
            logging.error(f"[Watchdog] Task {req_id} timed out after {self.timeout_sec}s! Respawning worker pool...")
            self._respawn_all_workers()
            return {
                "status_code": 503,
                "status": "INTERNAL_ERROR",
                "message": f"Search worker timed out (> {self.timeout_sec}s) or hung. Worker process respawned by Watchdog supervisor.",
                "state_machine": sm.get_summary()
            }

        if response.get("status") == "SUCCESS":
            sm.transition("COMPLETED")
        elif response.get("status") == "NO_COMMON":
            sm.transition("NO_RESULT")
        else:
            sm.transition("FAILED")

        sm.transition("RESPONDED")

        return {
            "status_code": 200,
            "status": response.get("status"),
            "mode": "TOGETHER",
            "data": response.get("data", []),
            "worker_pid": response.get("worker_pid"),
            "computation_ms": response.get("elapsed_ms", 0.0),
            "state_machine": sm.get_summary()
        }

    def shutdown(self):
        """Clean shutdown of worker processes."""
        logging.info("Shutting down E3 Orchestrator worker pool...")
        if self.task_queue:
            for _ in self.workers:
                self.task_queue.put({"action": "SHUTDOWN"})
        for pid, p in self.workers.items():
            if p.is_alive():
                p.terminate()

_orchestrator: Optional[SearchOrchestrator] = None

def get_orchestrator() -> Optional[SearchOrchestrator]:
    global _orchestrator
    # Guard against child processes spawning workers during Windows bootstrap
    if mp.current_process().name != "MainProcess":
        return None
    if _orchestrator is None:
        _orchestrator = SearchOrchestrator()
    return _orchestrator
