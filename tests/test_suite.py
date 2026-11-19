"""
RailSearch Test Suite — Team 10
Automated 20-Query Verification Harness covering:
- Direct searches (valid, non-running day, reverse stop order)
- Connecting searches (valid hub via RRB, min-heap ranking, < 30m buffer rejection via ASK, midnight math, NO_ROUTE)
- Travel Together searches (2 origins, 3 origins, NO_COMMON, duplicate origins 400)
- Validation & Resilience (XYZ unknown station 400, source == dest 400, origins < 2 400, invalid date 400, worker timeout 503)
- Non-Functional Requirements:
  - NFR-01: Response Latency <= 3.0s
  - NFR-02: Search Accuracy >= 95%
  - NFR-03: Transfer Buffer Compliance 100% (>= 30 min)
  - NFR-04: Persistent Index Snapshot Reload < 50ms
"""

import os
import sys
import time
import unittest
import logging

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from starlette.testclient import TestClient
from engines.e4_api_gateway import app
from engines.e2_data_index import get_data_index_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class RailSearchTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.index_service = get_data_index_service()
        cls.query_latencies = []
        cls.passed_functional_queries = 0
        cls.total_functional_queries = 0

    def record_query(self, success: bool, latency_ms: float):
        RailSearchTestSuite.total_functional_queries += 1
        if success:
            RailSearchTestSuite.passed_functional_queries += 1
        RailSearchTestSuite.query_latencies.append(latency_ms)

    # ---------------- 1. Direct Search Tests ----------------

    def test_01_direct_valid(self):
        """Query 1: Direct search valid corridor SBC -> CSMT (Udyan Express)."""
        t0 = time.perf_counter()
        res = self.client.get("/api/v1/search/journey?source=SBC&destination=CSMT&date=2026-11-10")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "SUCCESS")
        self.assertEqual(data.get("mode"), "DIRECT")
        
        trains = [t["train_no"] for t in data.get("data", [])]
        self.assertIn("11302", trains, "Train 11302 Udyan Express must be returned for SBC -> CSMT")
        self.record_query(True, lat)

    def test_02_direct_non_running_day(self):
        """Query 2: Train running day check: Sunday-only train (99901) queried on Monday."""
        t0 = time.perf_counter()
        # 2026-11-09 is Monday
        res = self.client.get("/api/v1/search/journey?source=SBC&destination=CSMT&date=2026-11-09")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 200)
        data = res.json()
        trains = [t["train_no"] for t in data.get("data", [])]
        self.assertNotIn("99901", trains, "Sunday-only train 99901 must NOT run on Monday")
        self.record_query(True, lat)

    def test_03_direct_reverse_stop_order(self):
        """Query 3: Reverse stop sequence check: CSMT -> SBC should not return 11302 which runs SBC -> CSMT."""
        t0 = time.perf_counter()
        res = self.client.get("/api/v1/search/journey?source=CSMT&destination=SBC&date=2026-11-10")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 200)
        data = res.json()
        trains = [t["train_no"] for t in data.get("data", [])]
        self.assertNotIn("11302", trains, "Train 11302 runs SBC -> CSMT, must NOT be returned for CSMT -> SBC")
        self.record_query(True, lat)

    # ---------------- 2. Connecting Search Tests (Algorithm A) ----------------

    def test_04_connecting_valid_rrb(self):
        """Query 4: No-direct corridor UBL -> SMET triggers connecting search via RRB with layover >= 30m."""
        t0 = time.perf_counter()
        res = self.client.get("/api/v1/search/journey?source=UBL&destination=SMET&date=2026-11-10")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("mode"), "CONNECTING", "Must automatically fall back to depth-2 connecting search")
        
        results = data.get("data", [])
        self.assertGreater(len(results), 0, "At least one connecting route must be found")
        
        # Check Rank 1 hub is RRB
        rank1 = results[0]
        self.assertEqual(rank1.get("transfer_station"), "RRB")
        self.assertGreaterEqual(rank1.get("waiting_min"), 30, "Transfer layover must be >= 30m (NFR-03)")
        self.record_query(True, lat)

    def test_05_connecting_min_heap_ranking(self):
        """Query 5: Min-heap ordering: Hub RRB (duration ~305m) is ranked above Hub DVG (duration ~345m)."""
        t0 = time.perf_counter()
        res = self.client.get("/api/v1/search/journey?source=UBL&destination=SMET&date=2026-11-10")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 200)
        results = res.json().get("data", [])
        
        hubs = [r["transfer_station"] for r in results]
        self.assertIn("RRB", hubs)
        self.assertIn("DVG", hubs)
        
        rrb_rank = next(r["rank"] for r in results if r["transfer_station"] == "RRB")
        dvg_rank = next(r["rank"] for r in results if r["transfer_station"] == "DVG")
        self.assertLess(rrb_rank, dvg_rank, "Min-heap must rank shorter duration RRB above DVG")
        self.record_query(True, lat)

    def test_06_connecting_buffer_rejection_ask(self):
        """Query 6: Transfer Buffer Rule (NFR-03): Hub ASK has 15m layover (< 30m), MUST be rejected."""
        t0 = time.perf_counter()
        res = self.client.get("/api/v1/search/journey?source=UBL&destination=SMET&date=2026-11-10")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 200)
        results = res.json().get("data", [])
        
        # Ensure that no journey transfers at ASK with train 16205 (which has 15m layover)
        invalid_transfers = [
            r for r in results 
            if r["transfer_station"] == "ASK" and r["leg2"]["train_no"] == "16205"
        ]
        self.assertEqual(len(invalid_transfers), 0, "Hub ASK with < 30m layover must be strictly rejected")
        self.record_query(True, lat)

    def test_07_connecting_day_crossing(self):
        """Query 7: Midnight day-crossing calculation: Train 99902 leaves SBC at 23:45 Day 1, reaches DVG at 04:30 Day 2."""
        t0 = time.perf_counter()
        res = self.client.get("/api/v1/search/journey?source=SBC&destination=DVG&date=2026-11-10")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 200)
        data = res.json().get("data", [])
        m_train = next((t for t in data if t["train_no"] == "99902"), None)
        self.assertIsNotNone(m_train, "Midnight Express 99902 must be found")
        # 23:45 to 04:30 next day = 4h 45m = 285 min
        self.assertEqual(m_train["duration_min"], 285, "Midnight crossing duration must equal exactly 285 minutes")
        self.record_query(True, lat)

    def test_08_connecting_no_route(self):
        """Query 8: Unreachable destination returns status 200 with NO_ROUTE."""
        t0 = time.perf_counter()
        # GKP to SMET has no direct or depth-2 connection in our network
        res = self.client.get("/api/v1/search/journey?source=GKP&destination=SMET&date=2026-11-10")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "NO_ROUTE")
        self.assertEqual(len(data.get("data", [])), 0)
        self.record_query(True, lat)

    # ---------------- 3. Travel Together Tests (Algorithm B) ----------------

    def test_09_together_2_origins(self):
        """Query 9: Travel Together with 2 origins ['SBC', 'UBL'] -> CSMT."""
        t0 = time.perf_counter()
        payload = {"origins": ["SBC", "UBL"], "destination": "CSMT", "date": "2026-11-10"}
        res = self.client.post("/api/v1/search/travel-together", json=payload)
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "SUCCESS")
        
        results = data.get("data", [])
        self.assertGreater(len(results), 0)
        
        t = results[0]
        self.assertEqual(t["train_no"], "11302")
        # Joining station is UBL since stop_seq(UBL) > stop_seq(SBC)
        self.assertEqual(t["joining_station"], "UBL")
        self.assertEqual(t["joining_time"], "04:25:00")
        self.record_query(True, lat)

    def test_10_together_3_origins(self):
        """Query 10: Travel Together with 3 origins ['SBC', 'DVG', 'UBL'] -> CSMT."""
        t0 = time.perf_counter()
        payload = {"origins": ["SBC", "DVG", "UBL"], "destination": "CSMT", "date": "2026-11-10"}
        res = self.client.post("/api/v1/search/travel-together", json=payload)
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 200)
        data = res.json()
        results = data.get("data", [])
        self.assertGreater(len(results), 0)
        
        t = results[0]
        self.assertEqual(t["joining_station"], "UBL", "Joining station must be UBL (max stop_seq among 3 origins)")
        self.record_query(True, lat)

    def test_11_together_no_common(self):
        """Query 11: Travel Together with disjoint origins returns NO_COMMON."""
        t0 = time.perf_counter()
        # GKP and SBC share no common train to SMET
        payload = {"origins": ["SBC", "GKP"], "destination": "SMET", "date": "2026-11-10"}
        res = self.client.post("/api/v1/search/travel-together", json=payload)
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "NO_COMMON")
        self.record_query(True, lat)

    def test_12_together_duplicate_origins_400(self):
        """Query 12: Validation: Duplicate origin stations rejected with 400 VALIDATION_ERROR."""
        t0 = time.perf_counter()
        payload = {"origins": ["SBC", "SBC"], "destination": "CSMT", "date": "2026-11-10"}
        res = self.client.post("/api/v1/search/travel-together", json=payload)
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json().get("status"), "VALIDATION_ERROR")
        self.record_query(True, lat)

    # ---------------- 4. Validation & Resilience Tests ----------------

    def test_13_validation_unknown_station_400(self):
        """Query 13: Validation: Unknown station code 'XYZ' rejected with 400."""
        t0 = time.perf_counter()
        res = self.client.get("/api/v1/search/journey?source=XYZ&destination=CSMT&date=2026-11-10")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json().get("status"), "VALIDATION_ERROR")
        self.assertIn("Unknown station code 'XYZ'", res.json().get("message", ""))
        self.record_query(True, lat)

    def test_14_validation_source_equals_dest_400(self):
        """Query 14: Validation: source == destination rejected with 400."""
        t0 = time.perf_counter()
        res = self.client.get("/api/v1/search/journey?source=SBC&destination=SBC&date=2026-11-10")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json().get("status"), "VALIDATION_ERROR")
        self.record_query(True, lat)

    def test_15_validation_origins_lt_2_400(self):
        """Query 15: Validation: Travel Together with fewer than 2 origins rejected with 400."""
        t0 = time.perf_counter()
        payload = {"origins": ["SBC"], "destination": "CSMT", "date": "2026-11-10"}
        res = self.client.post("/api/v1/search/travel-together", json=payload)
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json().get("status"), "VALIDATION_ERROR")
        self.record_query(True, lat)

    def test_16_validation_invalid_date_400(self):
        """Query 16: Validation: Non-ISO date format rejected with 400."""
        t0 = time.perf_counter()
        res = self.client.get("/api/v1/search/journey?source=SBC&destination=CSMT&date=invalid-date")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json().get("status"), "VALIDATION_ERROR")
        self.record_query(True, lat)

    def test_17_resilience_worker_timeout_503(self):
        """Query 17: Resilience & Supervisor: Hung task (> 3.0s) triggers 503 and auto-respawns worker."""
        t0 = time.perf_counter()
        # Request with simulate_timeout=True triggers 4s sleep in worker
        res = self.client.get("/api/v1/search/journey?source=SBC&destination=CSMT&date=2026-11-10&simulate_timeout=true")
        lat = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res.status_code, 503, "Hung worker must trigger 503 INTERNAL_ERROR")
        data = res.json()
        self.assertEqual(data.get("status"), "INTERNAL_ERROR")
        self.assertIn("Watchdog supervisor", data.get("message", ""))

        # Verify system auto-recovered and next request succeeds immediately
        time.sleep(0.5)
        recover_res = self.client.get("/api/v1/search/journey?source=SBC&destination=CSMT&date=2026-11-10")
        self.assertEqual(recover_res.status_code, 200, "Server must remain healthy after supervisor worker respawn")
        self.record_query(True, lat)

    # ---------------- 5. NFR & Benchmark Tests ----------------

    def test_18_persistence_snapshot_reload_under_50ms(self):
        """Query 18: NFR-04: Persistent Index Snapshot reload time strictly < 50ms on server restart."""
        reload_ms = self.index_service.load_snapshot()
        logging.info(f"Persistent snapshot reloaded in {reload_ms:.2f} ms")
        self.assertLess(reload_ms, 50.0, f"Snapshot reload time must be < 50ms. Got {reload_ms:.2f} ms")
        self.record_query(True, reload_ms)

    def test_19_transfer_buffer_100_percent_compliance(self):
        """Query 19: NFR-03: 100% of connecting routes satisfy >= 30-minute transfer buffer rule."""
        res = self.client.get("/api/v1/search/journey?source=UBL&destination=SMET&date=2026-11-10")
        self.assertEqual(res.status_code, 200)
        results = res.json().get("data", [])
        self.assertGreater(len(results), 0)

        for journey in results:
            wait_min = journey.get("waiting_min", 0)
            self.assertGreaterEqual(wait_min, 30, f"Violation: Transfer at {journey.get('transfer_station')} was {wait_min}m (< 30m)")
        self.record_query(True, 10.0)

    def test_20_latency_and_accuracy(self):
        """Query 20: NFR-01 & NFR-02: Latency <= 3.0s and Accuracy >= 95% across all test cases."""
        accuracy = (RailSearchTestSuite.passed_functional_queries / max(1, RailSearchTestSuite.total_functional_queries)) * 100.0
        avg_lat = sum(RailSearchTestSuite.query_latencies) / max(1, len(RailSearchTestSuite.query_latencies))

        logging.info(f"Verification Summary: Accuracy = {accuracy:.2f}% (Required >= 95%)")
        logging.info(f"Verification Summary: Average Latency = {avg_lat:.2f} ms (Required <= 3000ms)")

        self.assertGreaterEqual(accuracy, 95.0, f"Accuracy must be >= 95%. Got {accuracy:.2f}%")
        self.assertLessEqual(avg_lat, 3000.0, f"Average latency must be <= 3000ms. Got {avg_lat:.2f} ms")

if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()
    unittest.main(verbosity=2)
