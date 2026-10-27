"""Small transactional record store; each service owns a separate database."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))"
            )

    @contextmanager
    def transaction(self, *, timeout: float = 5) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=timeout)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, kind: str, key: str, *, timeout: float = 5) -> dict[str, Any] | None:
        # A status read must never acquire a writer reservation. SQLite permits
        # this SELECT while another connection holds BEGIN IMMEDIATE.
        db = sqlite3.connect(self.path, timeout=timeout)
        try:
            row = db.execute(
                "SELECT body FROM records WHERE kind=? AND id=?", (kind, key)
            ).fetchone()
            # Records are JSON object mappings written by put/write. Model-specific
            # validation remains the caller's canonical wire boundary.
            return cast(dict[str, Any], json.loads(row[0])) if row else None
        finally:
            db.close()

    def put(self, kind: str, key: str, value: dict[str, Any]) -> None:
        with self.transaction() as db:
            self.write(db, kind, key, value)

    @staticmethod
    def write(db: sqlite3.Connection, kind: str, key: str, value: dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
            (kind, key, json.dumps(value)),
        )


def wire[T: BaseModel](cls: type[T], data: object) -> T:
    """Canonical wire validation, preserving strict Python vs JSON distinction."""
    return cls.model_validate_json(json.dumps(data))
