"""
Engine E1 — Journey & Route Computation Worker Pool (Process Pool P3 · DSA & Discrete Math)
Consumes SearchTask payloads from IPC queue and executes:
1. Direct Search (Set intersection + sequence filter + day match)
2. Algorithm A: Two-Leg Connecting Search (Bounded BFS to depth 2, strict >= 30m buffer, min-heap priority queue)
3. Algorithm B: Travel Together Search (Multi-origin intersection, max(stop_seq) joining station & time)
"""

import os
import sys
import time
import heapq
import logging
from datetime import datetime
from typing import Dict, List, Set, Any, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [E1-WORKER] %(message)s")

DAYS_MAP = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

def time_to_min(time_str: str) -> int:
    """Converts HH:MM or HH:MM:SS string to continuous minutes within day."""
    if not time_str:
        return 0
    parts = time_str.strip().split(":")
    try:
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
        return hh * 60 + mm
    except (ValueError, IndexError):
        return 0

def min_to_time(minutes: int) -> str:
    """Converts continuous minutes to HH:MM format."""
    hh = (minutes // 60) % 24
    mm = minutes % 60
    return f"{hh:02d}:{mm:02d}"

def get_day_of_week(date_str: str) -> str:
    """Returns 3-letter uppercase day of week (MON-SUN) from YYYY-MM-DD."""
    dt = datetime.fromisoformat(date_str.strip())
    return DAYS_MAP[dt.weekday()]

def is_train_running(running_days: Set[str], req_date_str: str, stop_day_no: int) -> bool:
    """
    Checks if train runs such that it arrives at a station on req_date_str.
    stop_day_no is 1-indexed (Day 1, Day 2...).
    If passenger boards on req_date_str at Day stop_day_no, the train began its journey
    (stop_day_no - 1) days earlier.
    """
    if not running_days:
        return True # Default assume runs daily if not specified
    
    # Calculate starting day of week
    from datetime import timedelta
    req_dt = datetime.fromisoformat(req_date_str.strip())
    start_dt = req_dt - timedelta(days=(stop_day_no - 1))
    start_dow = DAYS_MAP[start_dt.weekday()]
    return start_dow in running_days

# ================= 1. DIRECT JOURNEY SEARCH =================

def search_direct(source: str, destination: str, date_str: str, index_service) -> List[Dict[str, Any]]:
    """
    Direct Search:
    Hash-map lookup of trains at source and destination, set intersection,
    filter by stop_seq(source) < stop_seq(destination) and RUNNING_DAY matching requested date.
    """
    src = source.strip().upper()
    dst = destination.strip().upper()

    if not index_service.stationExists(src) or not index_service.stationExists(dst):
        return []

    src_stops = index_service.station_trains.get(src, [])
    dst_stops = index_service.station_trains.get(dst, [])

    if not src_stops or not dst_stops:
        return []

    src_train_set = {s[0] for s in src_stops}
    dst_train_set = {s[0] for s in dst_stops}
    common_trains = src_train_set.intersection(dst_train_set)

    results = []
    for t_no in common_trains:
        s_stop = index_service.train_stop_map.get(t_no, {}).get(src)
        d_stop = index_service.train_stop_map.get(t_no, {}).get(dst)

        if not s_stop or not d_stop:
            continue

        # Enforce direction of travel
        if s_stop["stop_seq"] >= d_stop["stop_seq"]:
            continue

        # Check running days
        t_running = index_service.running_days.get(t_no, set())
        if not is_train_running(t_running, date_str, s_stop["day_no"]):
            continue

        # Calculate continuous minutes and total travel duration
        dep_min = time_to_min(s_stop["departure_time"])
        arr_min = time_to_min(d_stop["arrival_time"])
        day_diff = d_stop["day_no"] - s_stop["day_no"]
        
        duration_min = day_diff * 1440 + (arr_min - dep_min)
        if duration_min < 0:
            duration_min += 1440

        dur_h = duration_min // 60
        dur_m = duration_min % 60

        train_name = index_service.trains.get(t_no, {}).get("train_name", f"Train {t_no}")
        src_info = index_service.stations.get(src, {})
        dst_info = index_service.stations.get(dst, {})

        results.append({
            "mode": "DIRECT",
            "train_no": t_no,
            "train_name": train_name,
            "source": src,
            "source_name": src_info.get("station_name", src),
            "destination": dst,
            "destination_name": dst_info.get("station_name", dst),
            "departure_time": s_stop["departure_time"],
            "arrival_time": d_stop["arrival_time"],
            "departure_day_no": s_stop["day_no"],
            "arrival_day_no": d_stop["day_no"],
            "duration_min": duration_min,
            "duration_formatted": f"{dur_h}h {dur_m}m",
            "stops_count": d_stop["stop_seq"] - s_stop["stop_seq"],
            "running_days": sorted(list(t_running))
        })

    # Sort results by duration, then departure time
    results.sort(key=lambda r: (r["duration_min"], r["departure_time"]))
    return results

# ================= 2. ALGORITHM A: TWO-LEG CONNECTING SEARCH =================

def search_connecting(source: str, destination: str, date_str: str, index_service, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    Algorithm A — Two-Leg Connecting Search:
    - Bounded BFS to depth 2 (max 1 transfer / 2 legs).
    - Forward reachable set F from S.
    - Backward reachable set B to D.
    - Candidate transfer hubs = stations(F) ∩ stations(B).
    - Enforce Transfer Buffer Rule (NFR-03): layover >= 30 minutes!
    - Push feasible journeys into min-heap ordered by (totalDurationMin, waitingMin, legCount).
    - Return top-K ranked results.
    """
    src = source.strip().upper()
    dst = destination.strip().upper()

    if not index_service.stationExists(src) or not index_service.stationExists(dst):
        return []

    # Forward reachable set F from source:
    # Set of (transfer_station, train_1, s_stop, x_stop_1)
    F_trains = [s[0] for s in index_service.station_trains.get(src, [])]
    forward_stops = {} # X -> list of (T1, s_stop, x_stop)

    for t1 in F_trains:
        t1_stops = index_service.stopsOfTrain(t1)
        s_idx = -1
        for idx, st in enumerate(t1_stops):
            if st["station_code"] == src:
                s_idx = idx
                break
        if s_idx == -1:
            continue

        s_stop = t1_stops[s_idx]
        t1_running = index_service.running_days.get(t1, set())
        if not is_train_running(t1_running, date_str, s_stop["day_no"]):
            continue

        # All subsequent stops of T1 are forward reachable
        for x_stop in t1_stops[s_idx + 1:]:
            x_code = x_stop["station_code"]
            if x_code == dst:
                continue # Direct route handled separately
            if x_code not in forward_stops:
                forward_stops[x_code] = []
            forward_stops[x_code].append((t1, s_stop, x_stop))

    # Backward reachable set B reaching destination:
    # Set of (transfer_station, train_2, x_stop_2, d_stop)
    B_trains = [s[0] for s in index_service.station_trains.get(dst, [])]
    backward_stops = {} # X -> list of (T2, x_stop, d_stop)

    for t2 in B_trains:
        t2_stops = index_service.stopsOfTrain(t2)
        d_idx = -1
        for idx, st in enumerate(t2_stops):
            if st["station_code"] == dst:
                d_idx = idx
                break
        if d_idx == -1:
            continue

        d_stop = t2_stops[d_idx]
        # Preceding stops of T2 before D
        for x_stop in t2_stops[:d_idx]:
            x_code = x_stop["station_code"]
            if x_code == src:
                continue
            if x_code not in backward_stops:
                backward_stops[x_code] = []
            backward_stops[x_code].append((t2, x_stop, d_stop))

    # Candidate transfer stations: intersection of F and B
    candidate_hubs = set(forward_stops.keys()).intersection(set(backward_stops.keys()))
    if not candidate_hubs:
        return []

    # Priority queue min-heap for ranking
    min_heap = []
    seen_journey_signatures = set()
    counter = 0

    for hub in candidate_hubs:
        for t1, s_stop, x_stop1 in forward_stops[hub]:
            for t2, x_stop2, d_stop in backward_stops[hub]:
                if t1 == t2:
                    continue # Must be 2 distinct trains

                # Check if T2 runs
                t2_running = index_service.running_days.get(t2, set())

                # Leg 1 continuous timing
                t1_dep_min = time_to_min(s_stop["departure_time"])
                t1_arr_min = time_to_min(x_stop1["arrival_time"])
                leg1_days = x_stop1["day_no"] - s_stop["day_no"]
                leg1_dur = leg1_days * 1440 + (t1_arr_min - t1_dep_min)
                if leg1_dur < 0:
                    leg1_dur += 1440

                # Layover calculation at hub
                t2_dep_min = time_to_min(x_stop2["departure_time"])
                
                # Layover on same day
                layover_min = t2_dep_min - t1_arr_min
                if layover_min < 0:
                    layover_min += 1440 # Depart next calendar day

                # NFR-03 Strict Transfer Buffer Rule: Enforce >= 30 minutes!
                if layover_min < 30:
                    continue # REJECT! Insufficient buffer

                # Avoid unreasonable layovers (> 24 hours)
                if layover_min > 1440:
                    continue

                # Verify T2 runs on arrival day at hub
                from datetime import timedelta
                s_dt = datetime.fromisoformat(date_str.strip())
                hub_arrival_dt = s_dt + timedelta(days=leg1_days if t1_arr_min >= t1_dep_min else leg1_days + 1)
                if not is_train_running(t2_running, hub_arrival_dt.strftime("%Y-%m-%d"), x_stop2["day_no"]):
                    continue

                # Leg 2 continuous timing
                t2_arr_min = time_to_min(d_stop["arrival_time"])
                leg2_days = d_stop["day_no"] - x_stop2["day_no"]
                leg2_dur = leg2_days * 1440 + (t2_arr_min - t2_dep_min)
                if leg2_dur < 0:
                    leg2_dur += 1440

                total_duration_min = leg1_dur + layover_min + leg2_dur

                sig = (t1, hub, t2)
                if sig in seen_journey_signatures:
                    continue
                seen_journey_signatures.add(sig)

                hub_info = index_service.stations.get(hub, {})
                t1_name = index_service.trains.get(t1, {}).get("train_name", f"Train {t1}")
                t2_name = index_service.trains.get(t2, {}).get("train_name", f"Train {t2}")

                journey = {
                    "mode": "CONNECTING",
                    "total_duration_min": total_duration_min,
                    "total_duration_formatted": f"{total_duration_min // 60}h {total_duration_min % 60}m",
                    "waiting_min": layover_min,
                    "waiting_formatted": f"{layover_min // 60}h {layover_min % 60}m" if layover_min >= 60 else f"{layover_min}m",
                    "transfer_station": hub,
                    "transfer_station_name": hub_info.get("station_name", hub),
                    "leg_count": 2,
                    "leg1": {
                        "train_no": t1,
                        "train_name": t1_name,
                        "source": src,
                        "source_name": index_service.stations.get(src, {}).get("station_name", src),
                        "destination": hub,
                        "destination_name": hub_info.get("station_name", hub),
                        "departure_time": s_stop["departure_time"],
                        "arrival_time": x_stop1["arrival_time"],
                        "duration_min": leg1_dur,
                        "duration_formatted": f"{leg1_dur // 60}h {leg1_dur % 60}m"
                    },
                    "leg2": {
                        "train_no": t2,
                        "train_name": t2_name,
                        "source": hub,
                        "source_name": hub_info.get("station_name", hub),
                        "destination": dst,
                        "destination_name": index_service.stations.get(dst, {}).get("station_name", dst),
                        "departure_time": x_stop2["departure_time"],
                        "arrival_time": d_stop["arrival_time"],
                        "duration_min": leg2_dur,
                        "duration_formatted": f"{leg2_dur // 60}h {leg2_dur % 60}m"
                    }
                }

                # Push to min-heap ordered by (totalDurationMin, waitingMin, legCount)
                counter += 1
                heapq.heappush(min_heap, (total_duration_min, layover_min, 2, counter, journey))

    # Pop top-K ranked journeys from min-heap
    ranked_results = []
    rank = 1
    while min_heap and len(ranked_results) < max_results:
        _, _, _, _, item = heapq.heappop(min_heap)
        item["rank"] = rank
        ranked_results.append(item)
        rank += 1

    return ranked_results

# ================= 3. ALGORITHM B: TRAVEL TOGETHER SEARCH =================

def search_travel_together(origins: List[str], destination: str, date_str: str, index_service) -> Dict[str, Any]:
    """
    Algorithm B — Travel Together Search (Multi-Origin Group Search):
    - Input: origins = [O1, O2, ..., On] (n >= 2), destination = D, date.
    - For each origin Oi, find set Ti of trains stopping at Oi and later at D on date.
    - Compute Common = T1 ∩ T2 ∩ ... ∩ Tn.
    - If Common is empty, return NO_COMMON.
    - For each train T in Common:
      - joiningStation = origin Oi with largest stop_seq on train T.
      - joiningTime = departure time of train T at joiningStation.
    - Sort results by joining time / total duration to D.
    """
    dst = destination.strip().upper()
    clean_origins = [o.strip().upper() for o in origins]

    if not index_service.stationExists(dst):
        return {"status": "NO_COMMON", "results": []}

    origin_train_sets = []
    for origin in clean_origins:
        if not index_service.stationExists(origin):
            return {"status": "NO_COMMON", "results": []}

        trains_for_origin = set()
        st_stops = index_service.station_trains.get(origin, [])
        for t_no, seq, _, _, _ in st_stops:
            d_stop = index_service.train_stop_map.get(t_no, {}).get(dst)
            s_stop = index_service.train_stop_map.get(t_no, {}).get(origin)

            if s_stop and d_stop and s_stop["stop_seq"] < d_stop["stop_seq"]:
                t_running = index_service.running_days.get(t_no, set())
                if is_train_running(t_running, date_str, s_stop["day_no"]):
                    trains_for_origin.add(t_no)

        origin_train_sets.append(trains_for_origin)

    if not origin_train_sets:
        return {"status": "NO_COMMON", "results": []}

    # Discrete set intersection across all origins
    common_trains = origin_train_sets[0]
    for other_set in origin_train_sets[1:]:
        common_trains = common_trains.intersection(other_set)

    if not common_trains:
        return {"status": "NO_COMMON", "results": []}

    results = []
    dst_info = index_service.stations.get(dst, {})

    for t_no in common_trains:
        t_name = index_service.trains.get(t_no, {}).get("train_name", f"Train {t_no}")
        d_stop = index_service.train_stop_map[t_no][dst]

        # Determine boarding details for each origin
        boardings = []
        max_seq = -1
        joining_station_code = None
        joining_dep_time = None

        for origin in clean_origins:
            o_stop = index_service.train_stop_map[t_no][origin]
            o_info = index_service.stations.get(origin, {})
            seq = o_stop["stop_seq"]
            
            dep_m = time_to_min(o_stop["departure_time"])
            arr_m = time_to_min(d_stop["arrival_time"])
            days = d_stop["day_no"] - o_stop["day_no"]
            dur_m = days * 1440 + (arr_m - dep_m)
            if dur_m < 0:
                dur_m += 1440

            boardings.append({
                "origin": origin,
                "origin_name": o_info.get("station_name", origin),
                "stop_seq": seq,
                "departure_time": o_stop["departure_time"],
                "arrival_at_destination": d_stop["arrival_time"],
                "duration_min": dur_m,
                "duration_formatted": f"{dur_m // 60}h {dur_m % 60}m"
            })

            if seq > max_seq:
                max_seq = seq
                joining_station_code = origin
                joining_dep_time = o_stop["departure_time"]

        # Sort boardings by stop sequence (earliest origin first)
        boardings.sort(key=lambda b: b["stop_seq"])
        joining_station_name = index_service.stations.get(joining_station_code, {}).get("station_name", joining_station_code)

        # Remaining segment duration from joining station to destination
        j_stop = index_service.train_stop_map[t_no][joining_station_code]
        j_dep_m = time_to_min(j_stop["departure_time"])
        d_arr_m = time_to_min(d_stop["arrival_time"])
        rem_days = d_stop["day_no"] - j_stop["day_no"]
        together_dur = rem_days * 1440 + (d_arr_m - j_dep_m)
        if together_dur < 0:
            together_dur += 1440

        results.append({
            "mode": "TOGETHER",
            "train_no": t_no,
            "train_name": t_name,
            "destination": dst,
            "destination_name": dst_info.get("station_name", dst),
            "destination_arrival_time": d_stop["arrival_time"],
            "joining_station": joining_station_code,
            "joining_station_name": joining_station_name,
            "joining_time": joining_dep_time,
            "together_duration_min": together_dur,
            "together_duration_formatted": f"{together_dur // 60}h {together_dur % 60}m",
            "boardings": boardings
        })

    # Sort results by joining departure time
    results.sort(key=lambda r: (r["joining_time"], r["together_duration_min"]))
    return {"status": "SUCCESS", "results": results}

# ================= 4. IPC WORKER PROCESS TARGET =================

def worker_process_main(task_queue, response_queue, worker_id: int):
    """
    E1 Worker Process consumer loop:
    Consumes SearchTask dicts, executes computation via in-memory index, and returns SearchResponse.
    """
    logging.info(f"Worker PID {os.getpid()} (Worker-{worker_id}) started and loading index...")
    from engines.e2_data_index import get_data_index_service
    index_service = get_data_index_service()

    while True:
        try:
            task = task_queue.get()
            if task is None or task.get("action") == "SHUTDOWN":
                logging.info(f"Worker PID {os.getpid()} received shutdown signal.")
                break

            task_id = task.get("task_id")
            task_type = task.get("task_type")
            params = task.get("params", {})

            # Support simulated timeout testing
            if params.get("simulate_timeout"):
                sleep_dur = params.get("simulate_timeout_sec", 5.0)
                logging.warning(f"Worker PID {os.getpid()} simulating hung worker for {sleep_dur}s...")
                time.sleep(sleep_dur)

            t0 = time.perf_counter()
            response_data = None
            status = "SUCCESS"
            mode = "DIRECT"

            if task_type == "JOURNEY":
                src = params.get("source")
                dst = params.get("destination")
                dt = params.get("date")

                direct_res = search_direct(src, dst, dt, index_service)
                if direct_res:
                    response_data = direct_res
                    mode = "DIRECT"
                else:
                    connecting_res = search_connecting(src, dst, dt, index_service)
                    if connecting_res:
                        response_data = connecting_res
                        mode = "CONNECTING"
                    else:
                        response_data = []
                        mode = "NO_ROUTE"
                        status = "NO_ROUTE"

            elif task_type == "TOGETHER":
                origins = params.get("origins", [])
                dst = params.get("destination")
                dt = params.get("date")

                res_dict = search_travel_together(origins, dst, dt, index_service)
                response_data = res_dict.get("results", [])
                status = res_dict.get("status", "SUCCESS")
                mode = "TOGETHER"

            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            response = {
                "task_id": task_id,
                "status": status,
                "mode": mode,
                "data": response_data,
                "elapsed_ms": elapsed_ms,
                "worker_pid": os.getpid()
            }
            response_queue.put(response)

        except Exception as e:
            logging.error(f"Worker PID {os.getpid()} exception during task execution: {e}", exc_info=True)
            response_queue.put({
                "task_id": task.get("task_id") if "task" in locals() else "unknown",
                "status": "ERROR",
                "error": str(e),
                "worker_pid": os.getpid()
            })
