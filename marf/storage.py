"""SQLite storage: users, invoices, and an append-only audit log."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username     TEXT PRIMARY KEY,
    pw_hash      TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'user',
    failed_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    filename       TEXT NOT NULL,
    file_sha256    TEXT NOT NULL,
    stored_name    TEXT,
    vendor_name    TEXT,
    invoice_number TEXT,
    invoice_date   TEXT,
    currency       TEXT,
    subtotal       REAL,
    vat_amount     REAL,
    total          REAL,
    confidence     REAL,
    notes          TEXT,
    flags_json     TEXT NOT NULL DEFAULT '[]',
    status         TEXT NOT NULL DEFAULT 'pending',
    uploaded_by    TEXT NOT NULL,
    uploaded_at    TEXT NOT NULL,
    reviewed_by    TEXT,
    reviewed_at    TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    username TEXT NOT NULL,
    action   TEXT NOT NULL,
    detail   TEXT NOT NULL DEFAULT ''
);
"""

EDITABLE = ("vendor_name", "invoice_number", "invoice_date", "currency", "subtotal", "vat_amount", "total")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, db_path, upload_dir=None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir = Path(upload_dir) if upload_dir else self.db_path.parent / "uploads"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
        try:
            os.chmod(self.db_path, 0o600)  # owner-only; ignored on filesystems that don't support it
        except OSError:  # pragma: no cover
            pass

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- users -------------------------------------------------------------
    def add_user(self, username: str, pw_hash: str, role: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO users (username, pw_hash, role, created_at) VALUES (?,?,?,?)",
                (username, pw_hash, role, now_iso()),
            )

    def get_user(self, username: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def count_users(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def set_login_state(self, username: str, failed_count: int, locked_until: str | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET failed_count = ?, locked_until = ? WHERE username = ?",
                (failed_count, locked_until, username),
            )

    # ---- invoices ----------------------------------------------------------
    @staticmethod
    def _invoice(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["flags"] = json.loads(data.pop("flags_json") or "[]")
        return data

    def add_invoice(self, filename: str, file_sha256: str, stored_name: str, fields: dict, flags: list, uploaded_by: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO invoices
                   (filename, file_sha256, stored_name, vendor_name, invoice_number, invoice_date, currency,
                    subtotal, vat_amount, total, confidence, notes, flags_json, uploaded_by, uploaded_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    filename,
                    file_sha256,
                    stored_name,
                    fields.get("vendor_name"),
                    fields.get("invoice_number"),
                    fields.get("invoice_date"),
                    fields.get("currency"),
                    fields.get("subtotal"),
                    fields.get("vat_amount"),
                    fields.get("total"),
                    fields.get("confidence"),
                    fields.get("notes"),
                    json.dumps([f.to_dict() for f in flags]),
                    uploaded_by,
                    now_iso(),
                ),
            )
            return cur.lastrowid

    def update_invoice(self, invoice_id: int, fields: dict, flags: list) -> None:
        sets = ", ".join(f"{key} = ?" for key in EDITABLE)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE invoices SET {sets}, flags_json = ? WHERE id = ? AND status = 'pending'",
                (*[fields.get(key) for key in EDITABLE], json.dumps([f.to_dict() for f in flags]), invoice_id),
            )

    def set_status(self, invoice_id: int, status: str, reviewer: str, flags: list | None = None) -> None:
        with self._conn() as conn:
            if flags is not None:
                conn.execute("UPDATE invoices SET flags_json = ? WHERE id = ?", (json.dumps([f.to_dict() for f in flags]), invoice_id))
            conn.execute(
                "UPDATE invoices SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ? AND status = 'pending'",
                (status, reviewer, now_iso(), invoice_id),
            )

    def get_invoice(self, invoice_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        return self._invoice(row) if row else None

    def list_invoices(self, status: str | None = None) -> list[dict]:
        query, args = "SELECT * FROM invoices", ()
        if status:
            query, args = query + " WHERE status = ?", (status,)
        with self._conn() as conn:
            rows = conn.execute(query + " ORDER BY id DESC", args).fetchall()
        return [self._invoice(r) for r in rows]

    def file_path(self, invoice: dict) -> Path | None:
        name = invoice.get("stored_name")
        if not name or Path(name).name != name:  # never follow a path out of the upload folder
            return None
        path = self.upload_dir / name
        return path if path.exists() else None

    # ---- audit -------------------------------------------------------------
    def log(self, username: str, action: str, detail: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO audit (ts, username, action, detail) VALUES (?,?,?,?)",
                (now_iso(), username, action, detail[:1000]),
            )

    def list_audit(self, limit: int = 500) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT ts, username, action, detail FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---- retention ---------------------------------------------------------
    def purge_old_files(self, days: int) -> int:
        """Delete original files older than `days` (never ones still waiting for review).
        Extracted data and the audit log are kept. Returns the number of files removed."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        with self._conn() as conn:
            names = [
                r[0]
                for r in conn.execute(
                    """SELECT stored_name FROM invoices WHERE stored_name IS NOT NULL
                       GROUP BY stored_name
                       HAVING MAX(uploaded_at) < ? AND SUM(status = 'pending') = 0""",
                    (cutoff,),
                )
            ]
            removed = 0
            for name in names:
                if Path(name).name != name:
                    continue
                path = self.upload_dir / name
                if path.exists():
                    path.unlink()
                    removed += 1
                conn.execute("UPDATE invoices SET stored_name = NULL WHERE stored_name = ?", (name,))
        return removed
