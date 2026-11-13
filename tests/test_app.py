import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.api import app
from app.compute import MAX_N, count_primes
from app.db import claim_task, connect, init_db
from app.worker import process_one


class ApplicationTests(unittest.TestCase):
    def test_prime_counts(self):
        for n, expected in [(0, 0), (1, 0), (2, 1), (10, 4), (100, 25), (1_000_000, 78_498)]:
            with self.subTest(n=n):
                self.assertEqual(count_primes(n), expected)

    def test_compute_limits(self):
        for n in [-1, MAX_N + 1]:
            with self.assertRaises(ValueError):
                count_primes(n)

    def test_health(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})

    def test_invalid_requests(self):
        with TestClient(app) as client:
            for n in [-1, MAX_N + 1, 2.5, True, "10", None]:
                with self.subTest(n=n):
                    self.assertEqual(client.post("/tasks", json={"n": n}).status_code, 422)

    def test_readiness_without_configuration(self):
        with patch.dict(os.environ, {"DATABASE_URL": "", "PGHOST": ""}):
            with TestClient(app) as client:
                self.assertEqual(client.get("/ready").status_code, 503)

    def test_libpq_environment_configuration(self):
        with patch.dict(os.environ, {"DATABASE_URL": "", "PGHOST": "db"}):
            with patch("app.db.psycopg.connect") as mocked:
                connect()
                self.assertEqual(mocked.call_args.args, ("",))


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL not configured")
class PostgreSQLTests(unittest.TestCase):
    def setUp(self):
        self.url = os.environ["TEST_DATABASE_URL"]
        self.schema = "test_" + uuid.uuid4().hex
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        url = make_conninfo(self.url, options=f"-csearch_path={self.schema}")
        self.env = patch.dict(os.environ, {"DATABASE_URL": url})
        self.env.start()
        self.addCleanup(self.env.stop)
        init_db()

    def drop_schema(self):
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def test_api_and_workers(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/ready").status_code, 200)
            self.assertEqual(client.get("/tasks/999999").status_code, 404)
            ids = []
            for _ in range(12):
                response = client.post("/tasks", json={"n": 100})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["status"], "PENDING")
                ids.append(response.json()["id"])
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = list(pool.map(process_one, [f"worker-{i % 4}" for i in range(12)]))
            self.assertTrue(all(outcomes))
            self.assertFalse(process_one("idle-worker"))
            for task_id in ids:
                task = client.get(f"/tasks/{task_id}").json()
                self.assertEqual(task["status"], "COMPLETED")
                self.assertEqual(task["result"], 25)
                self.assertIsNotNone(task["finished_at"])
            self.assertEqual(len(client.get("/tasks").json()), 12)

    def test_concurrent_claims_are_unique(self):
        with connect() as conn:
            conn.execute("INSERT INTO tasks (n) SELECT 10 FROM generate_series(1, 20)")
        with ThreadPoolExecutor(max_workers=8) as pool:
            tasks = list(pool.map(claim_task, [f"worker-{i}" for i in range(30)]))
        claimed = [task for task in tasks if task is not None]
        self.assertEqual(len(claimed), 20)
        self.assertEqual(len({task["id"] for task in claimed}), 20)
        self.assertTrue(all(task["status"] == "RUNNING" for task in claimed))

    def test_failed_calculation(self):
        with connect() as conn:
            task_id = conn.execute("INSERT INTO tasks (n) VALUES (10) RETURNING id").fetchone()["id"]
        with patch("app.worker.count_primes", side_effect=ValueError("Test failure")):
            self.assertTrue(process_one("failing-worker"))
        with connect() as conn:
            task = conn.execute("SELECT * FROM tasks WHERE id = %s", (task_id,)).fetchone()
        self.assertEqual(task["status"], "FAILED")
        self.assertEqual(task["error"], "Test failure")


if __name__ == "__main__":
    unittest.main()
