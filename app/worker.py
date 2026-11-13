import logging
import os
import signal
import socket
import threading
import uuid

import psycopg

from app.compute import count_primes
from app.db import claim_task, connect


logger = logging.getLogger(__name__)


def process_one(worker_id: str) -> bool:
    task = claim_task(worker_id)
    if task is None:
        return False
    logger.info("Worker %s claimed task %s (n=%s)", worker_id, task["id"], task["n"])
    try:
        result = count_primes(task["n"])
    except Exception as exc:
        logger.exception("Task %s failed", task["id"])
        with connect() as conn:
            conn.execute(
                """UPDATE tasks SET status = 'FAILED', error = %s,
                   finished_at = CURRENT_TIMESTAMP WHERE id = %s""",
                (str(exc), task["id"]),
            )
    else:
        with connect() as conn:
            conn.execute(
                """UPDATE tasks SET status = 'COMPLETED', result = %s,
                   finished_at = CURRENT_TIMESTAMP WHERE id = %s""",
                (result, task["id"]),
            )
        logger.info("Task %s completed: %s primes", task["id"], result)
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not os.environ.get("DATABASE_URL") and not os.environ.get("PGHOST"):
        raise RuntimeError("DATABASE_URL or PGHOST must be set")
    interval = float(os.environ.get("POLL_INTERVAL", "1"))
    if not 0 < interval <= 60:
        raise ValueError("POLL_INTERVAL must be greater than 0 and at most 60 seconds")
    worker_id = os.environ.get("WORKER_ID") or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    logger.info("Starting worker %s", worker_id)
    while not stopping.is_set():
        try:
            if process_one(worker_id):
                continue
        except psycopg.Error:
            logger.exception("Database operation failed; retrying after polling interval")
        stopping.wait(interval)
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
