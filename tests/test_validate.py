from datetime import date
from decimal import Decimal

from marf.validate import (
    analyse,
    find_duplicates,
    has_errors,
    normalize_number,
    normalize_vendor,
    to_decimal,
    validate_fields,
)

TODAY = date(2026, 10, 30)


def good(**overrides):
    fields = {
        "vendor_name": "Demo Supplies W.L.L.",
        "invoice_number": "INV-2026-0412",
        "invoice_date": "2026-10-03",
        "currency": "BHD",
        "subtotal": 450.0,
        "vat_amount": 45.0,
        "total": 495.0,
        "confidence": 0.96,
    }
    fields.update(overrides)
    return fields


def codes(flags):
    return [f.code for f in flags]


def check(fields):
    return validate_fields(fields, today=TODAY, expected_currency="BHD")


def test_clean_invoice_has_no_flags():
    assert check(good()) == []


def test_sum_mismatch_is_an_error():
    flags = check(good(total=350.0, subtotal=300.0, vat_amount=30.0))
    assert codes(flags) == ["sum_mismatch"]
    assert has_errors(flags)


def test_small_rounding_difference_is_tolerated():
    assert check(good(total=495.004)) == []


def test_missing_required_fields():
    flags = check(good(vendor_name=None, invoice_number="  ", invoice_date=None, total=None))
    assert {"missing_vendor_name", "missing_invoice_number", "missing_invoice_date", "missing_total"} <= set(codes(flags))


def test_bad_and_future_and_old_dates():
    assert "bad_date" in codes(check(good(invoice_date="03/10/2026")))
    assert "future_date" in codes(check(good(invoice_date="2026-12-01")))
    assert "old_date" in codes(check(good(invoice_date="2024-01-01")))


def test_vat_rate_warning_is_not_an_error():
    flags = check(good(subtotal=450.0, vat_amount=22.5, total=472.5))
    assert codes(flags) == ["vat_rate"]
    assert not has_errors(flags)


def test_low_confidence_and_other_currency():
    flags = check(good(confidence=0.5, currency="usd"))
    assert set(codes(flags)) == {"low_confidence", "other_currency"}


def test_negative_amount_is_a_warning():
    assert "negative_amount" in codes(check(good(subtotal=-450.0, vat_amount=-45.0, total=-495.0)))


def test_to_decimal_rejects_junk():
    assert to_decimal("1,200.000") == Decimal("1200.000")
    for junk in (None, "", "abc", float("nan"), float("inf"), True):
        assert to_decimal(junk) is None


def test_vendor_and_number_normalisation():
    assert normalize_vendor("Demo Supplies, W.L.L.") == normalize_vendor("demo  supplies W.L.L")
    assert normalize_vendor("شركة العينة للكهرباء") == normalize_vendor("شركة  العينة للكهرباء.")
    assert normalize_number("INV-2026-0412") == normalize_number("inv 2026 0412")


def existing(**overrides):
    row = {
        "id": 1,
        "status": "approved",
        "file_sha256": "aaa",
        "vendor_name": "Demo Supplies W.L.L.",
        "invoice_number": "INV-2026-0412",
        "invoice_date": "2026-10-03",
        "total": 495.0,
    }
    row.update(overrides)
    return row


def test_duplicate_file():
    flags = find_duplicates(good(), "aaa", [existing()])
    assert codes(flags) == ["duplicate_file"] and has_errors(flags)


def test_duplicate_invoice_number_even_if_formatted_differently():
    flags = find_duplicates(good(invoice_number="inv 2026 0412"), "bbb", [existing()])
    assert codes(flags) == ["duplicate_invoice"]


def test_possible_duplicate_same_vendor_date_total():
    flags = find_duplicates(good(invoice_number="INV-9999"), "bbb", [existing()])
    assert codes(flags) == ["possible_duplicate"]
    assert not has_errors(flags)


def test_rejected_and_self_are_ignored():
    assert find_duplicates(good(), "aaa", [existing(status="rejected")]) == []
    assert find_duplicates(good(), "aaa", [existing(id=7)], exclude_id=7) == []


def test_different_vendor_same_number_is_not_a_duplicate():
    assert find_duplicates(good(vendor_name="Someone Else"), "bbb", [existing()]) == []


def test_unusual_amount_needs_history_and_a_big_jump():
    history = [existing(id=i, total=100.0, invoice_number=f"N{i}", file_sha256=str(i)) for i in range(1, 4)]
    big = good(invoice_number="N9", subtotal=1000.0, vat_amount=100.0, total=1100.0)
    assert "unusual_amount" in codes(analyse(big, "zzz", history, today=TODAY))
    assert "unusual_amount" not in codes(analyse(big, "zzz", history[:2], today=TODAY))


def test_errors_are_listed_first():
    flags = analyse(good(total=999.0, confidence=0.5), "x", [], today=TODAY)
    assert flags[0].severity == "error"
