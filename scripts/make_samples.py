#!/usr/bin/env python3
"""Generate FICTIONAL sample invoices plus samples/expected.json (used by demo mode and tests).

Needs Pillow, arabic-reshaper and python-bidi (see requirements-dev.txt). The generated files
are committed to the repo, so you only need to run this if you want to change the samples.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont, features

OUT = Path(__file__).resolve().parent.parent / "samples"
W, H = 1240, 1754

REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]
BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


@lru_cache(maxsize=None)
def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    for candidate in BOLD if bold else REGULAR:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    raise SystemExit("No Arabic-capable font found. Install DejaVu Sans or Arial and retry.")


def has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


RAQM = features.check("raqm")  # Pillow's own Arabic shaping and bidi, when available


def shape(text: str) -> str:
    # With raqm, Pillow already joins letters and orders right-to-left text; doing it again
    # would reverse the text. Without raqm, do it here.
    return text if RAQM else get_display(arabic_reshaper.reshape(text))


class Page:
    def __init__(self, rtl: bool = False):
        self.rtl = rtl
        self.img = Image.new("RGB", (W, H), "white")
        self.d = ImageDraw.Draw(self.img)

    def _x(self, x: int) -> int:
        return W - x if self.rtl else x

    def text(self, x, y, s, size=28, bold=False, fill=(25, 25, 25), align="start"):
        if has_arabic(s):
            s = shape(s)
        anchor = {"start": "r" if self.rtl else "l", "end": "l" if self.rtl else "r", "center": "m"}[align]
        self.d.text((self._x(x), y), s, font=font(bold, size), fill=fill, anchor=anchor + "a")

    def rect(self, x1, y1, x2, y2, fill):
        a, b = sorted((self._x(x1), self._x(x2)))
        self.d.rectangle((a, y1, b, y2), fill=fill)

    def line(self, y, x1=80, x2=W - 80, fill=(190, 190, 190), width=2):
        a, b = sorted((self._x(x1), self._x(x2)))
        self.d.line((a, y, b, y), fill=fill, width=width)


LABELS_EN = dict(
    title="TAX INVOICE", number="Invoice No", date="Date", bill_to="Bill to", desc="Description", qty="Qty",
    unit="Unit price", amount="Amount", subtotal="Subtotal", vat="VAT 10%", total="Total",
    sample="SAMPLE: fictional invoice for software demonstration only",
)
LABELS_AR = dict(
    title="فاتورة ضريبية", number="رقم الفاتورة", date="التاريخ", bill_to="العميل", desc="الوصف", qty="الكمية",
    unit="سعر الوحدة", amount="المبلغ", subtotal="المجموع الفرعي", vat="ضريبة القيمة المضافة 10%", total="الإجمالي",
    sample="نموذج: فاتورة وهمية لأغراض العرض فقط",
)
LABELS_BI = dict(
    title="Tax Invoice / فاتورة ضريبية", number="Invoice No / رقم الفاتورة", date="Date / التاريخ",
    bill_to="Bill to / العميل", desc="Description / الوصف", qty="Qty / الكمية", unit="Unit / السعر",
    amount="Amount / المبلغ", subtotal="Subtotal / المجموع الفرعي", vat="VAT 10% / الضريبة", total="Total / الإجمالي",
    sample="SAMPLE: fictional invoice / نموذج: فاتورة وهمية",
)


def render(spec: dict, path: Path) -> None:
    L = spec["labels"]
    p = Page(rtl=spec["rtl"])
    p.rect(0, 0, W, 190, (28, 58, 92))
    p.text(80, 55, spec["vendor"], 46, True, "white")
    p.text(80, 122, spec["tagline"], 24, False, (205, 218, 232))
    p.text(80, 250, L["title"], 54, True)
    p.text(80, 345, f'{L["number"]}: {spec["number"]}', 30)
    p.text(80, 392, f'{L["date"]}: {spec["date_str"]}', 30)
    p.text(80, 439, f'{L["bill_to"]}: {spec["bill_to"]}', 30)

    y = 540
    p.rect(80, y, W - 80, y + 64, (232, 238, 245))
    p.text(100, y + 16, L["desc"], 26, True)
    p.text(700, y + 16, L["qty"], 26, True, align="end")
    p.text(930, y + 16, L["unit"], 26, True, align="end")
    p.text(W - 100, y + 16, L["amount"], 26, True, align="end")
    y += 64
    for desc, qty, unit in spec["items"]:
        y += 18
        p.text(100, y, desc, 28)
        p.text(700, y, str(qty), 28, align="end")
        p.text(930, y, f"{unit:,.3f}", 28, align="end")
        p.text(W - 100, y, f"{qty * unit:,.3f}", 28, align="end")
        y += 52
        p.line(y)

    y += 44
    for i, (label, value) in enumerate(((L["subtotal"], spec["subtotal"]), (L["vat"], spec["vat"]), (L["total"], spec["total"]))):
        bold = i == 2
        if bold:
            p.line(y - 10, 480, W - 80, (60, 60, 60), 3)
            y += 8
        p.text(480, y, f'{label} ({spec["currency"]})', 30, bold)
        p.text(W - 100, y, f"{value:,.3f}", 30, bold, align="end")
        y += 54

    p.text(W // 2, H - 110, L["sample"], 24, False, (130, 130, 130), "center")

    if path.suffix == ".pdf":
        p.img.save(path, "PDF", resolution=150.0)
    else:
        p.img.save(path, optimize=True)


def build(filename, vendor, tagline, number, date_str, iso_date, bill_to, items, labels, rtl=False, printed_total=None):
    subtotal = round(sum(q * u for _, q, u in items), 3)
    vat = round(subtotal * 0.10, 3)
    total = printed_total if printed_total is not None else round(subtotal + vat, 3)
    return filename, dict(
        vendor=vendor, tagline=tagline, number=number, date_str=date_str, iso_date=iso_date, bill_to=bill_to,
        items=items, labels=labels, rtl=rtl, currency="BHD", subtotal=subtotal, vat=vat, total=total,
    )


GULF_ITEMS = [("A4 paper (box of 5 reams)", 10, 12.5), ("Toner cartridge", 5, 45.0), ("Cleaning liquid 5L", 10, 10.0)]

SPECS = [
    build("inv_01_demo_supplies_en.png", "Demo Supplies W.L.L.", "Office and cleaning supplies, Manama, Bahrain",
          "INV-2026-0412", "03 Oct 2026", "2026-10-03", "Example Plaza Management", GULF_ITEMS, LABELS_EN),
    build("inv_02_arabic_electrical_ar.png", "شركة العينة للكهرباء", "أعمال الكهرباء والصيانة، المنامة، البحرين",
          "7781", "2026-10-07", "2026-10-07", "إدارة مجمع المثال",
          [("مصابيح LED", 40, 4.5), ("كابلات كهربائية", 20, 18.0), ("أعمال تركيب وصيانة", 1, 660.0)], LABELS_AR, rtl=True),
    # The printed total is wrong on purpose (350.000 instead of 330.000) so the checks have something to catch.
    build("inv_03_demo_cleaning_total_error.png", "Demo Cleaning Services", "Janitorial services, Riffa, Bahrain",
          "DCS-1093", "12 Oct 2026", "2026-10-12", "Example Plaza Management",
          [("Monthly cleaning, common areas", 1, 250.0), ("Window cleaning", 1, 50.0)], LABELS_EN, printed_total=350.0),
    # Same vendor and invoice number as inv_01, sent again as a second file: a duplicate.
    build("inv_04_demo_supplies_duplicate.png", "Demo Supplies W.L.L.", "Office and cleaning supplies, Manama, Bahrain",
          "INV-2026-0412", "03 Oct 2026", "2026-10-03", "Example Plaza Mgmt.", GULF_ITEMS, LABELS_EN),
    build("inv_05_demo_cooling_bilingual.pdf", "Demo Cooling & AC Co.", "شركة العينة للتبريد والتكييف، المنامة",
          "AC-5520", "21 Oct 2026", "2026-10-21", "Example Plaza Management",
          [("AC maintenance contract Q4", 1, 2000.0), ("Compressor replacement", 1, 500.0)], LABELS_BI),
]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    expected = {}
    for filename, spec in SPECS:
        render(spec, OUT / filename)
        expected[filename] = {
            "vendor_name": spec["vendor"],
            "invoice_number": spec["number"],
            "invoice_date": spec["iso_date"],
            "currency": spec["currency"],
            "subtotal": spec["subtotal"],
            "vat_amount": spec["vat"],
            "total": spec["total"],
            "confidence": 0.96,
            "notes": None,
        }
        print("wrote", filename)
    (OUT / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote expected.json")


if __name__ == "__main__":
    main()
