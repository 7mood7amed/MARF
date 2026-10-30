import zipfile
from datetime import date
from io import BytesIO

from openpyxl import load_workbook

from marf.export import build_workbook


def invoice(i, **overrides):
    row = {
        "id": i,
        "invoice_number": f"INV-{i}",
        "vendor_name": "Demo Supplies W.L.L.",
        "invoice_date": "2026-10-03",
        "currency": "BHD",
        "subtotal": 450.0,
        "vat_amount": 45.0,
        "total": 495.0,
        "reviewed_by": "sara",
        "reviewed_at": "2026-10-30T10:00:00+00:00",
        "flags": [],
        "filename": "a.png",
    }
    row.update(overrides)
    return row


def open_sheet(data: bytes):
    return load_workbook(BytesIO(data)).active


def test_amounts_and_dates_are_real_numbers_and_dates():
    ws = open_sheet(build_workbook([invoice(1)]))
    assert [c.value for c in ws[1]][:3] == ["Invoice #", "Vendor", "Date"]
    assert ws["C2"].value.date() == date(2026, 10, 3)
    assert ws["G2"].value == 495.0 and ws["G2"].number_format == "#,##0.000"
    assert ws.freeze_panes == "A2"


def test_rows_are_sorted_by_invoice_date():
    ws = open_sheet(build_workbook([invoice(1, invoice_date="2026-10-20"), invoice(2, invoice_date="2026-10-02")]))
    assert [ws["A2"].value, ws["A3"].value] == ["INV-2", "INV-1"]


def test_text_from_invoices_can_never_become_a_formula():
    nasty = ['=HYPERLINK("http://evil.example","click")', "+cmd|' /C calc'!A0", "@SUM(1+1)", "-2+3"]
    data = build_workbook([invoice(i, vendor_name=text, invoice_number=text) for i, text in enumerate(nasty, 1)])

    ws = open_sheet(data)
    for row, text in enumerate(nasty, start=2):
        assert ws.cell(row=row, column=2).value == text
        assert ws.cell(row=row, column=2).data_type == "s"

    with zipfile.ZipFile(BytesIO(data)) as z:
        sheet_xml = z.read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet_xml


def test_flags_are_listed_and_empty_export_still_opens():
    flagged = invoice(1, flags=[{"code": "sum_mismatch", "severity": "error", "message": "x"}])
    assert open_sheet(build_workbook([flagged]))["J2"].value == "sum_mismatch"
    assert open_sheet(build_workbook([])).max_row == 1
