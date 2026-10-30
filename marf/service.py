"""Business logic between the UI and storage: upload, edit, approve, reject."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

from . import config
from .extract import extract_invoice
from .storage import EDITABLE, Storage
from .validate import AMOUNT_FIELDS, FIELD_LABELS, analyse, to_decimal


class UploadError(Exception):
    """The file was rejected before anything was read from it."""


class ReviewError(Exception):
    """A review action could not be completed."""


_SIGNATURES = ((b"%PDF-", ".pdf"), (b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"))


def detect_extension(data: bytes) -> str | None:
    """Decide the file type from its first bytes, not from the name the uploader gave it."""
    for signature, ext in _SIGNATURES:
        if data.startswith(signature):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def safe_filename(name) -> str:
    base = Path(str(name).replace("\\", "/")).name
    cleaned = "".join(ch for ch in base if ch.isprintable())[:120]
    return cleaned or "invoice"


def _analyse(storage: Storage, fields: dict, sha: str, exclude_id: int | None = None):
    return analyse(
        fields,
        sha,
        storage.list_invoices(),
        exclude_id=exclude_id,
        vat_rate=Decimal(config.VAT_RATE),
        expected_currency=config.DEFAULT_CURRENCY,
    )


def process_upload(storage: Storage, filename: str, data: bytes, username: str, extractor=extract_invoice) -> int:
    """Validate the upload, read it, run the checks, and queue it for human review."""
    name = safe_filename(filename)
    if not data:
        raise UploadError("The file is empty.")
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise UploadError(f"The file is larger than {config.MAX_UPLOAD_MB} MB.")
    ext = detect_extension(data)
    if ext is None:
        raise UploadError("Only PDF, PNG, JPG and WEBP files are accepted.")

    sha = hashlib.sha256(data).hexdigest()
    stored_name = f"{sha}{ext}"  # the stored name never comes from the uploader
    path = storage.upload_dir / stored_name
    created = not path.exists()
    if created:
        path.write_bytes(data)
    try:
        fields = extractor(path, name)
    except Exception as exc:
        if created:
            path.unlink(missing_ok=True)
        storage.log(username, "extract_failed", f"{name}: {type(exc).__name__}")
        raise

    flags = _analyse(storage, fields, sha)
    invoice_id = storage.add_invoice(name, sha, stored_name, fields, flags, username)
    storage.log(username, "upload", f"#{invoice_id} {name}; flags: {', '.join(f.code for f in flags) or 'none'}")
    return invoice_id


def _pending(storage: Storage, invoice_id: int) -> dict:
    invoice = storage.get_invoice(invoice_id)
    if invoice is None:
        raise ReviewError("Invoice not found.")
    if invoice["status"] != "pending":
        raise ReviewError(f"Invoice is already {invoice['status']}.")
    return invoice


def _parse_value(key: str, raw):
    text = "" if raw is None else str(raw).strip()
    if key in AMOUNT_FIELDS:
        if text == "":
            return None
        value = to_decimal(text)
        if value is None:
            raise ReviewError(f"{FIELD_LABELS[key]} is not a number.")
        return float(value)
    if key == "currency":
        return text.upper()[:8] or None
    return text[:200] or None


def update_fields(storage: Storage, invoice_id: int, new_values: dict, username: str) -> dict:
    """Save a person's corrections and re-run every check."""
    invoice = _pending(storage, invoice_id)
    updated = {key: _parse_value(key, new_values.get(key, invoice.get(key))) for key in EDITABLE}
    changes = [f"{key}: {invoice.get(key)!r} -> {updated[key]!r}" for key in EDITABLE if updated[key] != invoice.get(key)]
    flags = _analyse(storage, {**updated, "confidence": invoice["confidence"]}, invoice["file_sha256"], invoice_id)
    storage.update_invoice(invoice_id, updated, flags)
    if changes:
        storage.log(username, "edit", f"#{invoice_id} " + "; ".join(changes))
    return storage.get_invoice(invoice_id)


def approve(storage: Storage, invoice_id: int, username: str, override: bool = False) -> None:
    invoice = _pending(storage, invoice_id)
    flags = _analyse(storage, invoice, invoice["file_sha256"], invoice_id)
    errors = [f for f in flags if f.severity == "error"]
    if errors and not override:
        raise ReviewError("There are errors to fix. If you checked the invoice yourself and it is correct, tick the confirmation box.")
    storage.set_status(invoice_id, "approved", username, flags)
    detail = f"#{invoice_id}"
    if errors:
        detail += " WITH OVERRIDE of: " + ", ".join(f.code for f in errors)
    storage.log(username, "approve", detail)


def reject(storage: Storage, invoice_id: int, username: str) -> None:
    _pending(storage, invoice_id)
    storage.set_status(invoice_id, "rejected", username)
    storage.log(username, "reject", f"#{invoice_id}")
