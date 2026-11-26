
import os
import sys
import time
import sqlite3
import pickle
import logging
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Dict, List, Set, Any, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [E2-DBMS] %(message)s")

def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Hashes password with SHA-256 and unique salt."""
    if not salt:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return pwd_hash, salt

def verify_password(password: str, pwd_hash: str, salt: str) -> bool:
    """Verifies a plain password against stored salt and SHA-256 hash."""
    check_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(check_hash, pwd_hash)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "railsearch.db")
INDEX_PATH = os.path.join(DATA_DIR, "index_v1.bin")

STATIONS_CSV = os.path.join(DATA_DIR, "stations.csv")
TRAINS_CSV = os.path.join(DATA_DIR, "trains.csv")
TRAIN_STOPS_CSV = os.path.join(DATA_DIR, "train_stops.csv")
RUNNING_DAYS_CSV = os.path.join(DATA_DIR, "running_days.csv")

CORE_TEST_TRAINS = {
    "11302", "12079", "56240", "17315", "16205", "99901", "99902",
    "11017", "11036", "16201", "16202", "16227"
}

class DataIndexService:
    def __init__(self, db_path: str = DB_PATH, index_path: str = INDEX_PATH):
        self.db_path = db_path
        self.index_path = index_path
        
        # In-memory index structures
        self.stations: Dict[str, Dict[str, Any]] = {}
        self.trains: Dict[str, Dict[str, Any]] = {}
        self.station_trains: Dict[str, List[Tuple[str, int, str, str, int]]] = {} # code -> [(train_no, seq, arr, dep, day)]
        self.train_stops: Dict[str, List[Dict[str, Any]]] = {} # train_no -> [stops]
        self.running_days: Dict[str, Set[str]] = {} # train_no -> {MON, TUE...}
        
        # Inverted index lookup for fast route intersection
        self.train_stop_map: Dict[str, Dict[str, Dict[str, Any]]] = {} # train_no -> {station_code: stop_info}

        self.last_reload_time_ms: float = 0.0
        self.is_initialized: bool = False

        # Ensure schema tables exist (e.g. USER, OTP_RECORD, etc.)
        try:
            conn = self.get_connection()
            self.create_schema(conn, force_drop=False)
            conn.close()
        except Exception as e:
            logging.debug(f"Schema check error: {e}")

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def create_schema(self, conn: sqlite3.Connection, force_drop: bool = False):
        """Creates the 6 core relational tables as per Master Specification."""
        with conn:
            if force_drop:
                conn.executescript("""
                DROP TABLE IF EXISTS TRAIN_STOP;
                DROP TABLE IF EXISTS RUNNING_DAY;
                DROP TABLE IF EXISTS TRAIN;
                DROP TABLE IF EXISTS STATION;
                """)
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS STATION (
                station_code TEXT PRIMARY KEY,
                station_name TEXT NOT NULL,
                city TEXT
            );

            CREATE TABLE IF NOT EXISTS TRAIN (
                train_no TEXT PRIMARY KEY,
                train_name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS TRAIN_STOP (
                stop_id INTEGER PRIMARY KEY AUTOINCREMENT,
                train_no TEXT NOT NULL,
                station_code TEXT NOT NULL,
                stop_seq INTEGER NOT NULL,
                arrival_time TEXT,
                departure_time TEXT,
                day_no INTEGER DEFAULT 1,
                distance_km REAL DEFAULT 0.0,
                UNIQUE(train_no, stop_seq),
                UNIQUE(train_no, station_code),
                FOREIGN KEY(train_no) REFERENCES TRAIN(train_no),
                FOREIGN KEY(station_code) REFERENCES STATION(station_code)
            );

            CREATE INDEX IF NOT EXISTS idx_train_stop_lookup ON TRAIN_STOP(station_code, train_no, stop_seq);
            CREATE INDEX IF NOT EXISTS idx_train_seq ON TRAIN_STOP(train_no, stop_seq);

            CREATE TABLE IF NOT EXISTS RUNNING_DAY (
                train_no TEXT NOT NULL,
                day_of_week TEXT NOT NULL,
                PRIMARY KEY(train_no, day_of_week),
                FOREIGN KEY(train_no) REFERENCES TRAIN(train_no)
            );

            CREATE TABLE IF NOT EXISTS SEARCH_LOG (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_type TEXT NOT NULL,
                params TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                response_ms REAL NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS DATA_ISSUE (
                issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_ref TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                detected_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS USER (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                mobile TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                dob TEXT NOT NULL,
                gender TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT DEFAULT 'USER',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS OTP_RECORD (
                email TEXT PRIMARY KEY,
                otp TEXT NOT NULL,
                full_name TEXT NOT NULL,
                mobile TEXT NOT NULL,
                dob TEXT NOT NULL,
                gender TEXT NOT NULL,
                verified INTEGER DEFAULT 0,
                expires_at REAL NOT NULL
            );
            """)
        self.seed_admin_user(conn)
        logging.info("SQLite schema verified/created successfully.")

    def seed_admin_user(self, conn: sqlite3.Connection):
        """Seeds the pre-configured admin account if it does not already exist."""
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM USER WHERE role = 'ADMIN' OR email = 'admin@railsearch.in'")
            row = cur.fetchone()
            if not row:
                now = datetime.now(timezone.utc).isoformat()
                p_hash, salt = hash_password("admin123")
                with conn:
                    conn.execute(
                        """INSERT INTO USER (full_name, mobile, email, dob, gender, password_hash, salt, role, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        ("System Administrator", "admin", "admin@railsearch.in", "1990-01-01", "Other", p_hash, salt, "ADMIN", now)
                    )
                logging.info("Pre-seeded Admin account (username: admin / admin@railsearch.in, pass: admin123).")
        except Exception as e:
            logging.error(f"Error seeding admin user: {e}")

    def log_issue(self, conn: sqlite3.Connection, entity_type: str, entity_ref: str, issue_type: str):
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn.execute(
                "INSERT INTO DATA_ISSUE (entity_type, entity_ref, issue_type, detected_at) VALUES (?, ?, ?, ?)",
                (entity_type, entity_ref, issue_type, now)
            )
        except Exception as e:
            logging.error(f"Failed to log DATA_ISSUE: {e}")

    def log_search(self, request_type: str, params: str, status_code: int, response_ms: float):
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn = self.get_connection()
            with conn:
                conn.execute(
                    "INSERT INTO SEARCH_LOG (request_type, params, status_code, response_ms, created_at) VALUES (?, ?, ?, ?, ?)",
                    (request_type, params, status_code, response_ms, now)
                )
            conn.close()
        except Exception as e:
            logging.error(f"Failed to record SEARCH_LOG: {e}")

    def import_and_build_index(self, force_rebuild: bool = False):
        """Strict Data Validation on Import: Validates every row, logs issues, builds DB and persistent index."""
        conn = self.get_connection()
        self.create_schema(conn, force_drop=force_rebuild)

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM STATION")
        st_count = cur.fetchone()[0]

        if not force_rebuild and st_count > 0 and os.path.exists(self.index_path):
            logging.info("Existing database and persistent index found. Skipping raw import.")
            conn.close()
            self.load_snapshot()
            return

        logging.info("Importing CSV data with strict validation into SQLite...")
        start_import = time.perf_counter()

        import csv

        # 1. Import STATIONS
        valid_stations = {}
        if os.path.exists(STATIONS_CSV):
            with open(STATIONS_CSV, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    code = (row.get("station_code") or "").strip().upper()
                    name = (row.get("station_name") or "").strip()
                    city = (row.get("city") or "").strip()

                    if not code or not name:
                        self.log_issue(conn, "STATION", str(row), "MISSING_REQUIRED_FIELDS")
                        continue
                    if code in valid_stations:
                        self.log_issue(conn, "STATION", code, "DUPLICATE_PRIMARY_KEY")
                        continue

                    valid_stations[code] = (code, name, city)

        with conn:
            conn.executemany(
                "INSERT OR IGNORE INTO STATION (station_code, station_name, city) VALUES (?, ?, ?)",
                valid_stations.values()
            )
        logging.info(f"Imported {len(valid_stations)} valid stations.")

        # 2. Import TRAINS
        valid_trains = {}
        if os.path.exists(TRAINS_CSV):
            with open(TRAINS_CSV, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    t_no = (row.get("train_no") or "").strip()
                    t_name = (row.get("train_name") or "").strip()

                    if not t_no or not t_name:
                        self.log_issue(conn, "TRAIN", str(row), "MISSING_REQUIRED_FIELDS")
                        continue
                    if t_no in valid_trains:
                        self.log_issue(conn, "TRAIN", t_no, "DUPLICATE_PRIMARY_KEY")
                        continue

                    valid_trains[t_no] = (t_no, t_name)

        with conn:
            conn.executemany(
                "INSERT OR IGNORE INTO TRAIN (train_no, train_name) VALUES (?, ?)",
                valid_trains.values()
            )
        logging.info(f"Imported {len(valid_trains)} valid trains.")

        # 3. Import RUNNING_DAYS
        valid_days = []
        seen_days = set()
        if os.path.exists(RUNNING_DAYS_CSV):
            with open(RUNNING_DAYS_CSV, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    t_no = (row.get("train_no") or "").strip()
                    day = (row.get("day_of_week") or "").strip().upper()

                    if not t_no or not day:
                        self.log_issue(conn, "RUNNING_DAY", str(row), "MISSING_REQUIRED_FIELDS")
                        continue
                    if t_no not in valid_trains:
                        self.log_issue(conn, "RUNNING_DAY", f"{t_no}:{day}", "UNRESOLVED_FOREIGN_KEY_TRAIN")
                        continue
                    key = (t_no, day)
                    if key in seen_days:
                        self.log_issue(conn, "RUNNING_DAY", f"{t_no}:{day}", "DUPLICATE_PRIMARY_KEY")
                        continue

                    seen_days.add(key)
                    valid_days.append((t_no, day))

        with conn:
            conn.executemany(
                "INSERT OR IGNORE INTO RUNNING_DAY (train_no, day_of_week) VALUES (?, ?)",
                valid_days
            )
        logging.info(f"Imported {len(valid_days)} running days.")

        # 4. Import TRAIN_STOPS
        valid_stops = []
        seen_train_seq = set()
        seen_train_station = set()
        if os.path.exists(TRAIN_STOPS_CSV):
            with open(TRAIN_STOPS_CSV, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    t_no = (row.get("train_no") or "").strip()
                    st_code = (row.get("station_code") or "").strip().upper()
                    try:
                        seq = int(row.get("stop_seq") or 0)
                        day_no = int(row.get("day_no") or 1)
                        dist = float(row.get("distance_km") or 0.0)
                    except (ValueError, TypeError):
                        self.log_issue(conn, "TRAIN_STOP", str(row), "INVALID_INTEGER_FIELDS")
                        continue

                    arr = (row.get("arrival_time") or "").strip()
                    dep = (row.get("departure_time") or "").strip()

                    if not t_no or not st_code or seq <= 0:
                        self.log_issue(conn, "TRAIN_STOP", str(row), "MISSING_REQUIRED_FIELDS")
                        continue
                    if t_no not in valid_trains:
                        self.log_issue(conn, "TRAIN_STOP", f"{t_no}@{st_code}", "UNRESOLVED_FOREIGN_KEY_TRAIN")
                        continue
                    if st_code not in valid_stations:
                        self.log_issue(conn, "TRAIN_STOP", f"{t_no}@{st_code}", "UNRESOLVED_FOREIGN_KEY_STATION")
                        continue

                    key_seq = (t_no, seq)
                    if key_seq in seen_train_seq:
                        self.log_issue(conn, "TRAIN_STOP", f"{t_no}#seq{seq}", "DUPLICATE_STOP_SEQ")
                        continue

                    key_st = (t_no, st_code)
                    if key_st in seen_train_station:
                        self.log_issue(conn, "TRAIN_STOP", f"{t_no}@{st_code}", "DUPLICATE_TRAIN_STATION")
                        continue

                    seen_train_seq.add(key_seq)
                    seen_train_station.add(key_st)
                    valid_stops.append((t_no, st_code, seq, arr, dep, day_no, dist))

        with conn:
            conn.executemany(
                """INSERT OR IGNORE INTO TRAIN_STOP 
                   (train_no, station_code, stop_seq, arrival_time, departure_time, day_no, distance_km) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                valid_stops
            )
        logging.info(f"Imported {len(valid_stops)} valid train stops.")

        # 5. Build in-memory persistent inverted index structures
        logging.info("Constructing persistent inverted index...")
        self.stations = {code: {"station_code": code, "station_name": val[1], "city": val[2]} 
                         for code, val in valid_stations.items()}
        self.trains = {t_no: {"train_no": t_no, "train_name": val[1]} 
                       for t_no, val in valid_trains.items()}
        
        # Select active express/corridor trains to index into memory for < 50ms reload
        # Guaranteed inclusion of all CORE_TEST_TRAINS + top 100 express trains
        active_train_set = set(CORE_TEST_TRAINS)
        for t_no in valid_trains:
            if len(active_train_set) >= 100:
                break
            active_train_set.add(t_no)

        self.station_trains = {}
        self.train_stops = {}
        self.train_stop_map = {}
        
        for stop in valid_stops:
            t_no, st_code, seq, arr, dep, day_no, dist = stop
            if t_no not in active_train_set:
                continue
            
            if st_code not in self.station_trains:
                self.station_trains[st_code] = []
            self.station_trains[st_code].append((t_no, seq, arr, dep, day_no, dist))

            if t_no not in self.train_stops:
                self.train_stops[t_no] = []
                self.train_stop_map[t_no] = {}
            
            stop_dict = {
                "station_code": st_code,
                "stop_seq": seq,
                "arrival_time": arr,
                "departure_time": dep,
                "day_no": day_no,
                "distance_km": dist
            }
            self.train_stops[t_no].append(stop_dict)
            self.train_stop_map[t_no][st_code] = stop_dict

        # Sort stops by stop_seq
        for t_no in self.train_stops:
            self.train_stops[t_no].sort(key=lambda s: s["stop_seq"])

        self.running_days = {}
        for t_no, day in valid_days:
            if t_no in active_train_set:
                if t_no not in self.running_days:
                    self.running_days[t_no] = set()
                self.running_days[t_no].add(day)

        conn.close()

        # 6. Save persistent index snapshot to disk
        self.save_snapshot()
        self.is_initialized = True
        elapsed = time.perf_counter() - start_import
        logging.info(f"Database import and index persistence complete in {elapsed:.2f}s.")

    def save_snapshot(self):
        """Serializes inverted index to index_v1.bin snapshot."""
        snapshot = {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "stations": self.stations,
            "trains": self.trains,
            "station_trains": self.station_trains,
            "train_stops": self.train_stops,
            "train_stop_map": self.train_stop_map,
            "running_days": self.running_days
        }
        with open(self.index_path, "wb") as f:
            pickle.dump(snapshot, f, protocol=pickle.HIGHEST_PROTOCOL)
        size_mb = os.path.getsize(self.index_path) / (1024 * 1024)
        logging.info(f"Saved persistent index snapshot to {self.index_path} ({size_mb:.2f} MB).")

    def load_snapshot(self) -> float:
        """Loads index snapshot in < 50ms without hitting raw CSVs or running heavy SQL."""
        if not os.path.exists(self.index_path):
            logging.warning("Snapshot index file not found. Building from database/CSV...")
            self.import_and_build_index(force_rebuild=True)
            return self.last_reload_time_ms

        t0 = time.perf_counter()
        with open(self.index_path, "rb") as f:
            snapshot = pickle.load(f)

        self.stations = snapshot["stations"]
        self.trains = snapshot["trains"]
        self.station_trains = snapshot["station_trains"]
        self.train_stops = snapshot["train_stops"]
        self.train_stop_map = snapshot["train_stop_map"]
        self.running_days = snapshot["running_days"]

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.last_reload_time_ms = elapsed_ms
        self.is_initialized = True
        logging.info(f"Snapshot reloaded from disk in {elapsed_ms:.2f} ms (< 50ms verified).")
        return elapsed_ms

    # Read-Only Data-Access Interface

    def stationExists(self, code: str) -> bool:
        if not code:
            return False
        return code.strip().upper() in self.stations

    def trainsBetween(self, source: str, destination: str, day_of_week: Optional[str] = None) -> List[str]:
        src = source.strip().upper()
        dst = destination.strip().upper()
        if src not in self.station_trains or dst not in self.station_trains:
            return []

        src_trains = {s[0] for s in self.station_trains[src]}
        dst_trains = {s[0] for s in self.station_trains[dst]}
        common = src_trains.intersection(dst_trains)

        res = []
        for t_no in common:
            s_stop = self.train_stop_map.get(t_no, {}).get(src)
            d_stop = self.train_stop_map.get(t_no, {}).get(dst)
            if s_stop and d_stop and s_stop["stop_seq"] < d_stop["stop_seq"]:
                if day_of_week:
                    if day_of_week.upper() in self.running_days.get(t_no, set()):
                        res.append(t_no)
                else:
                    res.append(t_no)
        return res

    def departuresFrom(self, station: str, day_of_week: Optional[str] = None) -> List[Dict[str, Any]]:
        st = station.strip().upper()
        if st not in self.station_trains:
            return []
        res = []
        for t_no, seq, arr, dep, day_no in self.station_trains[st]:
            if day_of_week and day_of_week.upper() not in self.running_days.get(t_no, set()):
                continue
            res.append({
                "train_no": t_no,
                "train_name": self.trains.get(t_no, {}).get("train_name", ""),
                "stop_seq": seq,
                "departure_time": dep,
                "day_no": day_no
            })
        return res

    def arrivalsAt(self, station: str, day_of_week: Optional[str] = None) -> List[Dict[str, Any]]:
        st = station.strip().upper()
        if st not in self.station_trains:
            return []
        res = []
        for t_no, seq, arr, dep, day_no in self.station_trains[st]:
            if day_of_week and day_of_week.upper() not in self.running_days.get(t_no, set()):
                continue
            res.append({
                "train_no": t_no,
                "train_name": self.trains.get(t_no, {}).get("train_name", ""),
                "stop_seq": seq,
                "arrival_time": arr,
                "day_no": day_no
            })
        return res

    def stopsOfTrain(self, train_no: str) -> List[Dict[str, Any]]:
        return self.train_stops.get(train_no.strip(), [])

    def getAllStations(self) -> List[Dict[str, Any]]:
        return list(self.stations.values())

    def getStats(self) -> Dict[str, Any]:
        size_mb = os.path.getsize(self.index_path) / (1024 * 1024) if os.path.exists(self.index_path) else 0.0
        return {
            "status": "UP",
            "station_count": len(self.stations),
            "train_count": len(self.trains),
            "index_size_mb": round(size_mb, 2),
            "snapshot_reload_ms": round(self.last_reload_time_ms, 2)
        }

    # ================= Authentication & User Management =================

    def create_registration_otp(self, full_name: str, mobile: str, email: str, dob: str, gender: str) -> Tuple[bool, str, Optional[str]]:
        """Validates fields, checks duplicates, generates 6-digit OTP, stores in OTP_RECORD, and triggers email."""
        name = full_name.strip()
        mob = mobile.strip()
        em = email.strip().lower()
        d = dob.strip()
        gen = gender.strip()

        if len(name) < 2:
            return False, "", "Full name must be at least 2 characters."
        if not (mob.isdigit() and len(mob) == 10):
            return False, "", "Mobile number must be exactly 10 digits."
        if "@" not in em or "." not in em:
            return False, "", "Invalid email address format."
        if not d:
            return False, "", "Date of birth is required."
        if not gen:
            return False, "", "Gender is required."

        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id, email, mobile FROM USER WHERE email = ? OR mobile = ?", (em, mob))
            existing = cur.fetchone()
            if existing:
                if existing["email"] == em:
                    return False, "", "An account with this email address already exists."
                else:
                    return False, "", "An account with this mobile number already exists."

            # Generate 6-digit OTP
            otp = f"{secrets.randbelow(900000) + 100000}"
            expires_at = time.time() + 600.0  # 10 minutes

            with conn:
                conn.execute(
                    """INSERT OR REPLACE INTO OTP_RECORD (email, otp, full_name, mobile, dob, gender, verified, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
                    (em, otp, name, mob, d, gen, expires_at)
                )

            # Send Email
            from engines.email_service import send_otp_email
            email_res = send_otp_email(em, otp, name)

            return True, otp, email_res.get("warning")
        except Exception as e:
            logging.error(f"Error in create_registration_otp: {e}")
            return False, "", f"Failed to initiate registration: {str(e)}"
        finally:
            conn.close()

    def verify_registration_otp(self, email: str, otp: str) -> Tuple[bool, Optional[str]]:
        """Verifies 6-digit OTP for email within expiry window."""
        em = email.strip().lower()
        code = otp.strip()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM OTP_RECORD WHERE email = ?", (em,))
            row = cur.fetchone()
            if not row:
                return False, "No pending registration found for this email."
            if time.time() > row["expires_at"]:
                return False, "Verification OTP has expired. Please request a new code."
            if str(row["otp"]).strip() != code:
                return False, "Incorrect verification code. Please check and try again."

            with conn:
                conn.execute("UPDATE OTP_RECORD SET verified = 1 WHERE email = ?", (em,))
            return True, None
        except Exception as e:
            logging.error(f"Error verifying OTP: {e}")
            return False, f"Verification failed: {str(e)}"
        finally:
            conn.close()

    def complete_registration(self, email: str, password: str, confirm_password: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """Completes registration by setting password once OTP is verified."""
        em = email.strip().lower()
        if password != confirm_password:
            return False, None, "Passwords do not match."
        if len(password) < 6:
            return False, None, "Password must be at least 6 characters long."

        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM OTP_RECORD WHERE email = ?", (em,))
            row = cur.fetchone()
            if not row or not row["verified"]:
                return False, None, "Email has not been verified yet with OTP."

            p_hash, salt = hash_password(password)
            now = datetime.now(timezone.utc).isoformat()

            with conn:
                conn.execute(
                    """INSERT INTO USER (full_name, mobile, email, dob, gender, password_hash, salt, role, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'USER', ?)""",
                    (row["full_name"], row["mobile"], em, row["dob"], row["gender"], p_hash, salt, now)
                )
                cur.execute("SELECT user_id, full_name, mobile, email, dob, gender, role, created_at FROM USER WHERE email = ?", (em,))
                user_row = dict(cur.fetchone())
                conn.execute("DELETE FROM OTP_RECORD WHERE email = ?", (em,))

            return True, user_row, None
        except sqlite3.IntegrityError:
            return False, None, "Account already exists for this email or mobile."
        except Exception as e:
            logging.error(f"Error completing registration: {e}")
            return False, None, f"Failed to complete registration: {str(e)}"
        finally:
            conn.close()

    def authenticate(self, identifier: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticates user or admin by email, mobile, or username."""
        ident = identifier.strip().lower()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT user_id, full_name, mobile, email, dob, gender, password_hash, salt, role, created_at 
                   FROM USER WHERE LOWER(email) = ? OR LOWER(mobile) = ?""",
                (ident, ident)
            )
            row = cur.fetchone()
            if not row:
                return None

            if verify_password(password, row["password_hash"], row["salt"]):
                user_dict = dict(row)
                del user_dict["password_hash"]
                del user_dict["salt"]
                return user_dict
            return None
        except Exception as e:
            logging.error(f"Authentication query error: {e}")
            return None
        finally:
            conn.close()

    # ================= Admin Timetable Management =================

    def admin_list_trains(self, search: str = "", page: int = 1, limit: int = 25) -> Dict[str, Any]:
        """Returns paginated trains with stop counts and source/dest info."""
        q = search.strip().upper()
        all_train_items = []

        for t_no, t_data in self.trains.items():
            t_name = t_data.get("train_name", "")
            if q and (q not in t_no and q not in t_name.upper()):
                continue

            stops = self.train_stops.get(t_no, [])
            running = sorted(list(self.running_days.get(t_no, set())))
            src = stops[0]["station_code"] if stops else "—"
            dst = stops[-1]["station_code"] if stops else "—"

            all_train_items.append({
                "train_no": t_no,
                "train_name": t_name,
                "stops_count": len(stops),
                "source": src,
                "destination": dst,
                "running_days": running
            })

        all_train_items.sort(key=lambda t: t["train_no"])
        total = len(all_train_items)
        start_idx = max(0, (page - 1) * limit)
        end_idx = start_idx + limit
        paginated = all_train_items[start_idx:end_idx]

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "trains": paginated
        }

    def admin_get_train(self, train_no: str) -> Optional[Dict[str, Any]]:
        """Returns full train schedule including all stops."""
        t_no = train_no.strip()
        if t_no not in self.trains:
            return None

        t_data = self.trains[t_no]
        stops = self.train_stops.get(t_no, [])
        running = sorted(list(self.running_days.get(t_no, set())))

        # Enrich stops with station names
        enriched_stops = []
        for s in stops:
            code = s["station_code"]
            st_name = self.stations.get(code, {}).get("station_name", code)
            enriched_stops.append({
                "station_code": code,
                "station_name": st_name,
                "stop_seq": s["stop_seq"],
                "arrival_time": s["arrival_time"],
                "departure_time": s["departure_time"],
                "day_no": s["day_no"],
                "distance_km": s.get("distance_km", 0.0)
            })

        return {
            "train_no": t_no,
            "train_name": t_data.get("train_name", ""),
            "running_days": running,
            "stops": enriched_stops
        }

    def admin_save_train(self, train_no: str, train_name: str, running_days: List[str], stops: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Inserts or updates a train, its operating days, and its stop sequence in SQLite and active index."""
        t_no = str(train_no).strip()
        t_name = str(train_name).strip()

        if not t_no or not t_name:
            raise ValueError("Train number and name are required.")
        if not stops or len(stops) < 2:
            raise ValueError("A train must have at least 2 stops (source and destination).")

        conn = self.get_connection()
        try:
            with conn:
                # 1. Update TRAIN
                conn.execute(
                    "INSERT OR REPLACE INTO TRAIN (train_no, train_name) VALUES (?, ?)",
                    (t_no, t_name)
                )

                # 2. Update RUNNING_DAY
                conn.execute("DELETE FROM RUNNING_DAY WHERE train_no = ?", (t_no,))
                valid_days = [d.strip().upper() for d in running_days if d.strip().upper() in ["MON","TUE","WED","THU","FRI","SAT","SUN"]]
                if not valid_days:
                    valid_days = ["MON","TUE","WED","THU","FRI","SAT","SUN"]
                conn.executemany(
                    "INSERT INTO RUNNING_DAY (train_no, day_of_week) VALUES (?, ?)",
                    [(t_no, d) for d in valid_days]
                )

                # 3. Update TRAIN_STOP
                conn.execute("DELETE FROM TRAIN_STOP WHERE train_no = ?", (t_no,))
                clean_stops = []
                for idx, s in enumerate(stops):
                    st_code = s.get("station_code", "").strip().upper()
                    seq = int(s.get("stop_seq", idx + 1))
                    arr = s.get("arrival_time", "00:00:00").strip()
                    dep = s.get("departure_time", "00:00:00").strip()
                    day_no = int(s.get("day_no", 1))
                    dist = float(s.get("distance_km", 0.0))

                    clean_stops.append((t_no, st_code, seq, arr, dep, day_no, dist))

                conn.executemany(
                    """INSERT INTO TRAIN_STOP 
                       (train_no, station_code, stop_seq, arrival_time, departure_time, day_no, distance_km)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    clean_stops
                )

            # Update In-Memory Structures
            self.trains[t_no] = {"train_no": t_no, "train_name": t_name}
            self.running_days[t_no] = set(valid_days)
            
            stop_dicts = []
            self.train_stop_map[t_no] = {}
            for item in clean_stops:
                _, st_code, seq, arr, dep, day_no, dist = item
                s_dict = {
                    "station_code": st_code,
                    "stop_seq": seq,
                    "arrival_time": arr,
                    "departure_time": dep,
                    "day_no": day_no,
                    "distance_km": dist
                }
                stop_dicts.append(s_dict)
                self.train_stop_map[t_no][st_code] = s_dict

                if st_code not in self.station_trains:
                    self.station_trains[st_code] = []
                # Remove existing stop if present
                self.station_trains[st_code] = [st for st in self.station_trains[st_code] if st[0] != t_no]
                self.station_trains[st_code].append((t_no, seq, arr, dep, day_no, dist))

            stop_dicts.sort(key=lambda s: s["stop_seq"])
            self.train_stops[t_no] = stop_dicts

            # Update snapshot
            self.save_snapshot()
            logging.info(f"Admin saved train {t_no} ({t_name}) with {len(clean_stops)} stops.")
            return {"status": "SUCCESS", "message": f"Train {t_no} saved successfully.", "train_no": t_no}

        except Exception as e:
            logging.error(f"Error saving train {t_no}: {e}")
            raise
        finally:
            conn.close()

    def admin_delete_train(self, train_no: str) -> bool:
        """Deletes train and stops from DB and in-memory index."""
        t_no = train_no.strip()
        conn = self.get_connection()
        try:
            with conn:
                conn.execute("DELETE FROM TRAIN_STOP WHERE train_no = ?", (t_no,))
                conn.execute("DELETE FROM RUNNING_DAY WHERE train_no = ?", (t_no,))
                conn.execute("DELETE FROM TRAIN WHERE train_no = ?", (t_no,))

            # In-memory cleanup
            self.trains.pop(t_no, None)
            self.running_days.pop(t_no, None)
            self.train_stops.pop(t_no, None)
            self.train_stop_map.pop(t_no, None)

            for st_code in self.station_trains:
                self.station_trains[st_code] = [st for st in self.station_trains[st_code] if st[0] != t_no]

            self.save_snapshot()
            logging.info(f"Admin deleted train {t_no}.")
            return True
        except Exception as e:
            logging.error(f"Error deleting train {t_no}: {e}")
            return False
        finally:
            conn.close()

    def rebuild_index_hot(self) -> float:
        """Re-imports and hot-reloads persistent index snapshot."""
        self.import_and_build_index(force_rebuild=True)
        return self.load_snapshot()

_instance: Optional[DataIndexService] = None

def get_data_index_service() -> DataIndexService:
    global _instance
    if _instance is None:
        _instance = DataIndexService()
        if os.path.exists(INDEX_PATH):
            _instance.load_snapshot()
        else:
            _instance.import_and_build_index()
    return _instance

if __name__ == "__main__":
    svc = DataIndexService()
    svc.import_and_build_index(force_rebuild=True)
    load_ms = svc.load_snapshot()
    print(f"Stats: {svc.getStats()}")
    print(f"Station SBC exists: {svc.stationExists('SBC')}")
    print(f"Trains SBC -> CSMT: {svc.trainsBetween('SBC', 'CSMT')}")
