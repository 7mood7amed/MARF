"""Excel export of approved invoices."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .validate import parse_date

# (header, key, width, kind)
COLUMNS = (
    ("Invoice #", "invoice_number", 18, "text"),
    ("Vendor", "vendor_name", 34, "text"),
    ("Date", "invoice_date", 12, "date"),
    ("Currency", "currency", 10, "text"),
    ("Subtotal", "subtotal", 14, "amount"),
    ("VAT", "vat_amount", 12, "amount"),
    ("Total", "total", 14, "amount"),
    ("Approved by", "reviewed_by", 14, "text"),
    ("Approved at (UTC)", "reviewed_at", 20, "text"),
    ("Flags at approval", "flags", 26, "flags"),
    ("Source file", "filename", 30, "text"),
)


def _set_text(cell, value) -> None:
    """Invoice text is untrusted. Force it to be stored as a plain string so a vendor
    named '=HYPERLINK(...)' can never become a formula when the sheet is opened."""
    cell.value = value
    if value is not None:
        cell.data_type = "s"


def build_workbook(invoices: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Invoices"

    header_fill = PatternFill("solid", start_color="1C3A5C")
    for col, (header, _key, width, _kind) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[cell.column_letter].width = width

    rows = sorted(invoices, key=lambda i: (i.get("invoice_date") or "", i["id"]))
    for row_no, inv in enumerate(rows, start=2):
        for col, (_header, key, _width, kind) in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=row_no, column=col)
            if kind == "amount":
                cell.value = inv.get(key)
                cell.number_format = "#,##0.000"
            elif kind == "date":
                parsed = parse_date(inv.get(key))
                if parsed:
                    cell.value = parsed
                    cell.number_format = "yyyy-mm-dd"
                else:
                    _set_text(cell, inv.get(key))
            elif kind == "flags":
                _set_text(cell, ", ".join(f["code"] for f in inv.get("flags", [])) or None)
            else:
                _set_text(cell, inv.get(key))

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
