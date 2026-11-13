import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def connect():
    url = os.environ.get("DATABASE_URL")
    if not url and not os.environ.get("PGHOST"):
        raise RuntimeError("DATABASE_URL or PGHOST must be set")
    return psycopg.connect(
        url or "", autocommit=True, row_factory=dict_row, connect_timeout=5
    )


def init_db():
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connect() as conn:
        with conn.transaction():
            conn.execute(schema)


def claim_task(worker_id: str):
    # The lock and status update belong to one atomic SQL statement/transaction.
    with connect() as conn:
        return conn.execute(
            """
            WITH candidate AS (
                SELECT id FROM tasks
                WHERE status = 'PENDING'
                ORDER BY id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE tasks AS t
            SET status = 'RUNNING', worker_id = %s,
                started_at = CURRENT_TIMESTAMP
            FROM candidate
            WHERE t.id = candidate.id
            RETURNING t.*
            """,
            (worker_id,),
        ).fetchone()


if __name__ == "__main__":
    init_db()
    print("Database schema initialized.")
