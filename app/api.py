from datetime import datetime
from typing import Literal

import psycopg
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.compute import MAX_N
from app.db import connect


app = FastAPI(title="Distributed Task Manager")


class TaskInput(BaseModel):
    n: int = Field(ge=0, le=MAX_N, strict=True)


class Task(BaseModel):
    id: int
    n: int
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
    result: int | None
    error: str | None
    worker_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    try:
        with connect() as conn:
            conn.execute("SELECT id FROM tasks LIMIT 0")
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Database unavailable or not initialized") from exc
    return {"status": "ready"}


@app.post("/tasks", response_model=Task, status_code=201)
def create_task(data: TaskInput):
    with connect() as conn:
        return conn.execute(
            "INSERT INTO tasks (n) VALUES (%s) RETURNING *", (data.n,)
        ).fetchone()


@app.get("/tasks", response_model=list[Task])
def list_tasks(limit: int = Query(default=100, ge=1, le=1000)):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM tasks ORDER BY id DESC LIMIT %s", (limit,)
        ).fetchall()


@app.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: int):
    with connect() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id = %s", (task_id,)).fetchone()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
