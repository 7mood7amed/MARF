"""Deterministic checks on extracted invoice data. The AI reads; plain code verifies.
Nothing here calls a model, so the checks are predictable and testable."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

REQUIRED = ("vendor_name", "invoice_number", "invoice_date", "total")

FIELD_LABELS = {
    "vendor_name": "Vendor",
    "invoice_number": "Invoice number",
    "invoice_date": "Invoice date",
    "currency": "Currency",
    "subtotal": "Subtotal",
    "vat_amount": "VAT",
    "total": "Total",
}

AMOUNT_FIELDS = ("subtotal", "vat_amount", "total")


@dataclass(frozen=True)
class Flag:
    code: str
    severity: str  # "error" blocks approval unless a person overrides; "warn" is informational
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def to_decimal(value) -> Decimal | None:
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_vendor(name) -> str:
    text = re.sub(r"[^\w\s]", " ", (name or "").casefold())
    return re.sub(r"\s+", " ", text).strip()


def normalize_number(number) -> str:
    return re.sub(r"[\s\-_/.]", "", (number or "").casefold())


def has_errors(flags) -> bool:
    return any((f.severity if isinstance(f, Flag) else f["severity"]) == "error" for f in flags)


def validate_fields(
    fields: dict,
    *,
    vat_rate: Decimal = Decimal("0.10"),
    today: date | None = None,
    tolerance: Decimal = Decimal("0.01"),
    expected_currency: str | None = None,
) -> list[Flag]:
    today = today or date.today()
    flags: list[Flag] = []

    for key in REQUIRED:
        value = fields.get(key)
        if value is None or str(value).strip() == "":
            flags.append(Flag(f"missing_{key}", "error", f"{FIELD_LABELS[key]} is missing."))

    raw_date = fields.get("invoice_date")
    if raw_date not in (None, ""):
        parsed = parse_date(raw_date)
        if parsed is None:
            flags.append(Flag("bad_date", "error", "Invoice date is not a valid date (use YYYY-MM-DD)."))
        elif parsed > today:
            flags.append(Flag("future_date", "warn", f"Invoice date {parsed} is in the future."))
        elif parsed < today - timedelta(days=400):
            flags.append(Flag("old_date", "warn", f"Invoice date {parsed} is more than a year old."))

    amounts: dict[str, Decimal | None] = {}
    for key in AMOUNT_FIELDS:
        raw = fields.get(key)
        amounts[key] = to_decimal(raw)
        if raw not in (None, "") and amounts[key] is None:
            flags.append(Flag(f"bad_{key}", "error", f"{FIELD_LABELS[key]} is not a valid number."))
        elif amounts[key] is not None and amounts[key] < 0:
            flags.append(Flag("negative_amount", "warn", f"{FIELD_LABELS[key]} is negative. Is this a credit note?"))

    subtotal, vat, total = amounts["subtotal"], amounts["vat_amount"], amounts["total"]
    if subtotal is not None and vat is not None and total is not None:
        if abs(subtotal + vat - total) > tolerance:
            flags.append(
                Flag(
                    "sum_mismatch",
                    "error",
                    f"Subtotal {subtotal:.3f} + VAT {vat:.3f} = {subtotal + vat:.3f}, but the total says {total:.3f}.",
                )
            )
    if subtotal not in (None, Decimal(0)) and vat is not None:
        expected_vat = subtotal * vat_rate
        if abs(vat - expected_vat) > Decimal("0.05"):
            flags.append(
                Flag(
                    "vat_rate",
                    "warn",
                    f"VAT is {vat:.3f}, but {vat_rate * 100:.0f}% of the subtotal would be {expected_vat:.3f}.",
                )
            )

    confidence = fields.get("confidence")
    if confidence is not None and float(confidence) < 0.8:
        flags.append(Flag("low_confidence", "warn", f"The reader was unsure ({float(confidence):.0%} confidence). Check every field."))

    currency = fields.get("currency")
    if expected_currency and currency and str(currency).upper() != expected_currency.upper():
        flags.append(Flag("other_currency", "warn", f"Currency is {currency}, not {expected_currency}."))

    return flags


def find_duplicates(fields: dict, file_sha256: str | None, others: list[dict], exclude_id: int | None = None) -> list[Flag]:
    """Compare against invoices already in the system (rejected ones are ignored)."""
    flags: list[Flag] = []
    vendor = normalize_vendor(fields.get("vendor_name"))
    number = normalize_number(fields.get("invoice_number"))
    total = to_decimal(fields.get("total"))
    inv_date = fields.get("invoice_date")

    for other in others:
        if other["id"] == exclude_id or other["status"] == "rejected":
            continue
        ref = f"invoice #{other['id']} ({other['status']})"
        if file_sha256 and other.get("file_sha256") == file_sha256:
            flags.append(Flag("duplicate_file", "error", f"This exact file was already uploaded as {ref}."))
            continue
        same_vendor = vendor and vendor == normalize_vendor(other.get("vendor_name"))
        if same_vendor and number and number == normalize_number(other.get("invoice_number")):
            flags.append(Flag("duplicate_invoice", "error", f"Same vendor and invoice number as {ref}."))
        elif (
            same_vendor
            and total is not None
            and inv_date
            and inv_date == other.get("invoice_date")
            and total == to_decimal(other.get("total"))
        ):
            flags.append(Flag("possible_duplicate", "warn", f"Same vendor, date and total as {ref}."))
    return flags


def check_unusual_amount(fields: dict, others: list[dict], exclude_id: int | None = None) -> list[Flag]:
    vendor = normalize_vendor(fields.get("vendor_name"))
    total = to_decimal(fields.get("total"))
    if not vendor or total is None:
        return []
    history = [
        to_decimal(o.get("total"))
        for o in others
        if o["id"] != exclude_id and o["status"] == "approved" and normalize_vendor(o.get("vendor_name")) == vendor
    ]
    history = [h for h in history if h is not None]
    if len(history) < 3:
        return []
    average = sum(history) / len(history)
    if average > 0 and total > average * 3:
        return [
            Flag(
                "unusual_amount",
                "warn",
                f"Total {total} is more than 3x this vendor's average ({average:.3f}) over {len(history)} approved invoices.",
            )
        ]
    return []


def analyse(
    fields: dict,
    file_sha256: str | None,
    existing: list[dict],
    *,
    exclude_id: int | None = None,
    vat_rate: Decimal = Decimal("0.10"),
    today: date | None = None,
    expected_currency: str | None = None,
) -> list[Flag]:
    """All checks together, errors listed first."""
    flags = validate_fields(fields, vat_rate=vat_rate, today=today, expected_currency=expected_currency)
    flags += find_duplicates(fields, file_sha256, existing, exclude_id)
    flags += check_unusual_amount(fields, existing, exclude_id)
    return sorted(flags, key=lambda f: f.severity != "error")
