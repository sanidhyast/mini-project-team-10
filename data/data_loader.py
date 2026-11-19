"""
RailSearch - Data Seeder & Normalizer
Extracts and normalizes raw Indian Railways data into stations.csv, trains.csv, train_stops.csv, running_days.csv.
Enriches with deterministic corridors specified in Engineering Requirements:
1. Direct Corridor: SBC -> CSMT (Train 11302 Udyan Express)
2. Travel Together Corridor: ['SBC', 'UBL'] -> CSMT (Train 11302, joining at UBL)
3. No-Direct / Connecting Corridor: UBL -> SMET via RRB (Layover 50m >= 30m, Rank 1)
   Alternative Hub: DVG (Layover 75m >= 30m, Rank 2)
   Alternative Hub: ASK (Layover 15m < 30m, REJECTED by Transfer Buffer Rule)
4. Non-running day special: 99901 (Sunday only)
"""

import os
import csv
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

RAW_DATASET_PATH = r"c:\Users\stpla\OneDrive\Desktop\MP\merged_railway_dataset.csv"
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

STATIONS_CSV = os.path.join(DATA_DIR, "stations.csv")
TRAINS_CSV = os.path.join(DATA_DIR, "trains.csv")
TRAIN_STOPS_CSV = os.path.join(DATA_DIR, "train_stops.csv")
RUNNING_DAYS_CSV = os.path.join(DATA_DIR, "running_days.csv")

DAYS_ALL = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

def build_datasets():
    logging.info("Starting dataset extraction and seeding...")

    stations = {}
    trains = {}
    train_stops = []
    running_days = []

    # 1. Add core test stations guaranteed
    core_stations = [
        {"station_code": "SBC", "station_name": "KSR Bengaluru City Junction", "city": "Bengaluru"},
        {"station_code": "UBL", "station_name": "SSS Hubballi Junction", "city": "Hubballi"},
        {"station_code": "RRB", "station_name": "Birur Junction", "city": "Birur"},
        {"station_code": "SMET", "station_name": "Shivamogga Town", "city": "Shivamogga"},
        {"station_code": "DVG", "station_name": "Davangere", "city": "Davangere"},
        {"station_code": "ASK", "station_name": "Arsikere Junction", "city": "Arsikere"},
        {"station_code": "CSMT", "station_name": "Chhatrapati Shivaji Maharaj Terminus", "city": "Mumbai"},
        {"station_code": "CSTM", "station_name": "Mumbai CSMT (Old Code)", "city": "Mumbai"},
        {"station_code": "YPR", "station_name": "Yesvantpur Junction", "city": "Bengaluru"},
        {"station_code": "BGM", "station_name": "Belagavi", "city": "Belagavi"},
        {"station_code": "PUNE", "station_name": "Pune Junction", "city": "Pune"},
        {"station_code": "KYN", "station_name": "Kalyan Junction", "city": "Kalyan"},
        {"station_code": "GKP", "station_name": "Gorakhpur Junction", "city": "Gorakhpur"},
        {"station_code": "NDLS", "station_name": "New Delhi", "city": "New Delhi"},
        {"station_code": "HWH", "station_name": "Howrah Junction", "city": "Kolkata"},
        {"station_code": "MAS", "station_name": "MGR Chennai Central", "city": "Chennai"}
    ]
    for s in core_stations:
        stations[s["station_code"]] = s

    # 2. Extract real data from merged_railway_dataset.csv if present
    TARGET_TRAIN_TYPES = {'Express', 'SF', 'Raj', 'Shtb', 'JShtb'}
    CORE_CODES = {s["station_code"] for s in core_stations}

    if os.path.exists(RAW_DATASET_PATH):
        logging.info(f"Scanning target express trains from {RAW_DATASET_PATH}...")
        try:
            target_train_ids = set()
            with open(RAW_DATASET_PATH, mode="r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    st_code = (row.get("station_code") or "").strip().upper()
                    t_no = (row.get("\ufefftrain_number") or row.get("train_number") or "").strip()
                    t_type = (row.get("train_type") or "").strip()
                    if st_code and st_code not in stations:
                        stations[st_code] = {
                            "station_code": st_code,
                            "station_name": (row.get("station_name") or "").strip(),
                            "city": (row.get("state") or "").strip()
                        }
                    if t_no and (st_code in CORE_CODES or t_type in TARGET_TRAIN_TYPES):
                        target_train_ids.add(t_no)

            logging.info(f"Identified {len(target_train_ids)} target express and corridor trains.")

            with open(RAW_DATASET_PATH, mode="r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    t_no = (row.get("\ufefftrain_number") or row.get("train_number") or "").strip()
                    if t_no not in target_train_ids:
                        continue
                    
                    st_code = (row.get("station_code") or "").strip().upper()
                    t_name = (row.get("train_name") or "").strip()

                    if t_no not in trains:
                        trains[t_no] = {
                            "train_no": t_no,
                            "train_name": t_name
                        }
                        rd_str = row.get("running_days") or ""
                        if rd_str:
                            for day in rd_str.split(","):
                                d = day.strip().upper()
                                if d in DAYS_ALL:
                                    running_days.append({"train_no": t_no, "day_of_week": d})
                        else:
                            for d in DAYS_ALL:
                                running_days.append({"train_no": t_no, "day_of_week": d})

                    if t_no and st_code:
                        try:
                            seq = int(row.get("station_sequence") or 0)
                            day_no = int(row.get("journey_day") or 1)
                        except (ValueError, TypeError):
                            seq = 0
                            day_no = 1
                        arr = (row.get("arrival_time") or "").strip()
                        dep = (row.get("departure_time") or "").strip()

                        if arr and len(arr) == 5:
                            arr += ":00"
                        if dep and len(dep) == 5:
                            dep += ":00"
                        if not arr and dep:
                            arr = dep
                        if not dep and arr:
                            dep = arr

                        if seq > 0 and (arr or dep):
                            train_stops.append({
                                "stop_id": len(train_stops) + 1,
                                "train_no": t_no,
                                "station_code": st_code,
                                "stop_seq": seq,
                                "arrival_time": arr,
                                "departure_time": dep,
                                "day_no": day_no
                            })

            logging.info(f"Loaded {len(stations)} stations, {len(trains)} trains, {len(train_stops)} stops from raw data.")
        except Exception as e:
            logging.warning(f"Error reading raw dataset: {e}")
    else:
        logging.warning("Raw dataset file not found, seeding purely deterministic dataset.")

    # 3. Deterministic Seed Corridors (as specified in Master Engineering Specification)
    logging.info("Injecting Master Engineering Specification seed corridors...")

    # Corridor 1 & Travel Together: Train 11302 (Udyan Express)
    # SBC -> YPR -> ASK -> RRB -> DVG -> UBL -> BGM -> PUNE -> KYN -> CSMT
    trains["11302"] = {"train_no": "11302", "train_name": "Udyan Express"}
    for d in DAYS_ALL:
        running_days.append({"train_no": "11302", "day_of_week": d})

    udyan_stops = [
        {"station_code": "SBC", "stop_seq": 1, "arr": "20:45:00", "dep": "20:45:00", "day": 1},
        {"station_code": "YPR", "stop_seq": 2, "arr": "20:55:00", "dep": "20:57:00", "day": 1},
        {"station_code": "ASK", "stop_seq": 3, "arr": "23:20:00", "dep": "23:25:00", "day": 1},
        {"station_code": "RRB", "stop_seq": 4, "arr": "00:08:00", "dep": "00:10:00", "day": 2},
        {"station_code": "DVG", "stop_seq": 5, "arr": "01:40:00", "dep": "01:42:00", "day": 2},
        {"station_code": "UBL", "stop_seq": 6, "arr": "04:15:00", "dep": "04:25:00", "day": 2},
        {"station_code": "BGM", "stop_seq": 7, "arr": "07:00:00", "dep": "07:05:00", "day": 2},
        {"station_code": "PUNE", "stop_seq": 8, "arr": "15:45:00", "dep": "15:50:00", "day": 2},
        {"station_code": "KYN", "stop_seq": 9, "arr": "18:40:00", "dep": "18:43:00", "day": 2},
        {"station_code": "CSMT", "stop_seq": 10, "arr": "20:15:00", "dep": "20:15:00", "day": 2},
    ]
    # Remove any existing 11302 stops and add deterministic
    train_stops = [s for s in train_stops if s["train_no"] != "11302"]
    for s in udyan_stops:
        train_stops.append({
            "stop_id": len(train_stops) + 1,
            "train_no": "11302",
            "station_code": s["station_code"],
            "stop_seq": s["stop_seq"],
            "arrival_time": s["arr"],
            "departure_time": s["dep"],
            "day_no": s["day"]
        })

    # Corridor 2: Connecting Corridor UBL -> SMET (No direct train between UBL and SMET)
    # Leg 1 Train: 12079 (Jan Shatabdi Express)
    # UBL (dep 06:00:00) -> DVG (arr 07:30, dep 07:35) -> RRB (arr 09:10, dep 09:15) -> ASK (arr 10:00, dep 10:05)
    trains["12079"] = {"train_no": "12079", "train_name": "Jan Shatabdi Express"}
    for d in DAYS_ALL:
        running_days.append({"train_no": "12079", "day_of_week": d})
    train_stops = [s for s in train_stops if s["train_no"] != "12079"]
    for s in [
        {"station_code": "UBL", "stop_seq": 1, "arr": "06:00:00", "dep": "06:00:00", "day": 1},
        {"station_code": "DVG", "stop_seq": 2, "arr": "07:30:00", "dep": "07:35:00", "day": 1},
        {"station_code": "RRB", "stop_seq": 3, "arr": "09:10:00", "dep": "09:15:00", "day": 1},
        {"station_code": "ASK", "stop_seq": 4, "arr": "10:00:00", "dep": "10:05:00", "day": 1},
    ]:
        train_stops.append({
            "stop_id": len(train_stops) + 1,
            "train_no": "12079",
            "station_code": s["station_code"],
            "stop_seq": s["stop_seq"],
            "arrival_time": s["arr"],
            "departure_time": s["dep"],
            "day_no": s["day"]
        })

    # Leg 2 via RRB: Train 56240 (Birur-Shivamogga Passenger)
    # Departs RRB at 10:00:00 (Layover at RRB = 10:00 - 09:10 = 50 min >= 30 min -> VALID)
    # Arrives SMET at 11:05:00 (Total duration from UBL = 305 min)
    trains["56240"] = {"train_no": "56240", "train_name": "Birur Shivamogga Passenger"}
    for d in DAYS_ALL:
        running_days.append({"train_no": "56240", "day_of_week": d})
    train_stops = [s for s in train_stops if s["train_no"] != "56240"]
    for s in [
        {"station_code": "RRB", "stop_seq": 1, "arr": "10:00:00", "dep": "10:00:00", "day": 1},
        {"station_code": "SMET", "stop_seq": 2, "arr": "11:05:00", "dep": "11:05:00", "day": 1},
    ]:
        train_stops.append({
            "stop_id": len(train_stops) + 1,
            "train_no": "56240",
            "station_code": s["station_code"],
            "stop_seq": s["stop_seq"],
            "arrival_time": s["arr"],
            "departure_time": s["dep"],
            "day_no": s["day"]
        })

    # Leg 2 Alternative via DVG: Train 17315 (Davangere-Shivamogga Link)
    # Departs DVG at 08:45:00 (Layover at DVG = 08:45 - 07:30 = 75 min >= 30 min -> VALID)
    # Arrives SMET at 11:45:00 (Total duration from UBL = 345 min -> Ranked #2 by Min-Heap)
    trains["17315"] = {"train_no": "17315", "train_name": "Davangere Shimoga Link"}
    for d in DAYS_ALL:
        running_days.append({"train_no": "17315", "day_of_week": d})
    train_stops = [s for s in train_stops if s["train_no"] != "17315"]
    for s in [
        {"station_code": "DVG", "stop_seq": 1, "arr": "08:45:00", "dep": "08:45:00", "day": 1},
        {"station_code": "SMET", "stop_seq": 2, "arr": "11:45:00", "dep": "11:45:00", "day": 1},
    ]:
        train_stops.append({
            "stop_id": len(train_stops) + 1,
            "train_no": "17315",
            "station_code": s["station_code"],
            "stop_seq": s["stop_seq"],
            "arrival_time": s["arr"],
            "departure_time": s["dep"],
            "day_no": s["day"]
        })

    # Buffer Rejection Test via ASK: Train 16205 (Arsikere-Shivamogga Shuttle)
    # Departs ASK at 10:15:00. Jan Shatabdi arrives ASK at 10:00:00.
    # Layover at ASK = 10:15 - 10:00 = 15 min (< 30 min -> REJECTED by NFR-03)
    trains["16205"] = {"train_no": "16205", "train_name": "Arsikere Shimoga Shuttle"}
    for d in DAYS_ALL:
        running_days.append({"train_no": "16205", "day_of_week": d})
    train_stops = [s for s in train_stops if s["train_no"] != "16205"]
    for s in [
        {"station_code": "ASK", "stop_seq": 1, "arr": "10:15:00", "dep": "10:15:00", "day": 1},
        {"station_code": "SMET", "stop_seq": 2, "arr": "11:30:00", "dep": "11:30:00", "day": 1},
    ]:
        train_stops.append({
            "stop_id": len(train_stops) + 1,
            "train_no": "16205",
            "station_code": s["station_code"],
            "stop_seq": s["stop_seq"],
            "arrival_time": s["arr"],
            "departure_time": s["dep"],
            "day_no": s["day"]
        })

    # Special Train: 99901 (Sunday Only express SBC -> CSMT)
    trains["99901"] = {"train_no": "99901", "train_name": "Sunday Special Express"}
    running_days.append({"train_no": "99901", "day_of_week": "SUN"})
    train_stops = [s for s in train_stops if s["train_no"] != "99901"]
    for s in [
        {"station_code": "SBC", "stop_seq": 1, "arr": "10:00:00", "dep": "10:00:00", "day": 1},
        {"station_code": "CSMT", "stop_seq": 2, "arr": "22:00:00", "dep": "22:00:00", "day": 1},
    ]:
        train_stops.append({
            "stop_id": len(train_stops) + 1,
            "train_no": "99901",
            "station_code": s["station_code"],
            "stop_seq": s["stop_seq"],
            "arrival_time": s["arr"],
            "departure_time": s["dep"],
            "day_no": s["day"]
        })

    # Day-crossing midnight test train: 99902 (Leaves SBC at 23:45 Day 1, arrives DVG at 04:30 Day 2)
    trains["99902"] = {"train_no": "99902", "train_name": "Midnight Express"}
    for d in DAYS_ALL:
        running_days.append({"train_no": "99902", "day_of_week": d})
    train_stops = [s for s in train_stops if s["train_no"] != "99902"]
    for s in [
        {"station_code": "SBC", "stop_seq": 1, "arr": "23:45:00", "dep": "23:45:00", "day": 1},
        {"station_code": "DVG", "stop_seq": 2, "arr": "04:30:00", "dep": "04:30:00", "day": 2},
    ]:
        train_stops.append({
            "stop_id": len(train_stops) + 1,
            "train_no": "99902",
            "station_code": s["station_code"],
            "stop_seq": s["stop_seq"],
            "arrival_time": s["arr"],
            "departure_time": s["dep"],
            "day_no": s["day"]
        })

    # Ensure deliberate malformed rows exist in a test staging file to verify DATA_ISSUE logging
    # 4. Write CSV files
    logging.info(f"Writing {STATIONS_CSV} ({len(stations)} records)...")
    with open(STATIONS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["station_code", "station_name", "city"])
        writer.writeheader()
        writer.writerows(stations.values())

    logging.info(f"Writing {TRAINS_CSV} ({len(trains)} records)...")
    with open(TRAINS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["train_no", "train_name"])
        writer.writeheader()
        writer.writerows(trains.values())

    # De-duplicate train_stops by (train_no, stop_seq) and (train_no, station_code)
    seen_stop_keys = set()
    seen_train_stations = set()
    valid_train_stops = []
    for s in train_stops:
        key1 = (s["train_no"], s["stop_seq"])
        key2 = (s["train_no"], s["station_code"])
        if key1 in seen_stop_keys or key2 in seen_train_stations:
            continue
        seen_stop_keys.add(key1)
        seen_train_stations.add(key2)
        valid_train_stops.append(s)

    logging.info(f"Writing {TRAIN_STOPS_CSV} ({len(valid_train_stops)} records)...")
    with open(TRAIN_STOPS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["stop_id", "train_no", "station_code", "stop_seq", "arrival_time", "departure_time", "day_no"])
        writer.writeheader()
        writer.writerows(valid_train_stops)

    # De-duplicate running_days by (train_no, day_of_week)
    seen_rd = set()
    valid_running_days = []
    for rd in running_days:
        key = (rd["train_no"], rd["day_of_week"])
        if key in seen_rd:
            continue
        seen_rd.add(key)
        valid_running_days.append(rd)

    logging.info(f"Writing {RUNNING_DAYS_CSV} ({len(valid_running_days)} records)...")
    with open(RUNNING_DAYS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["train_no", "day_of_week"])
        writer.writeheader()
        writer.writerows(valid_running_days)

    logging.info("Dataset files generated successfully!")

if __name__ == "__main__":
    build_datasets()
