import pytest

from marf import config, service

S1 = "inv_01_demo_supplies_en.png"
S2 = "inv_02_arabic_electrical_ar.png"
S3 = "inv_03_demo_cleaning_total_error.png"
S4 = "inv_04_demo_supplies_duplicate.png"
S5 = "inv_05_demo_cooling_bilingual.pdf"


def codes(invoice, severity=None):
    return [f["code"] for f in invoice["flags"] if severity in (None, f["severity"])]


def upload(storage, sample, name, user="sara"):
    return service.process_upload(storage, name, sample(name), user)


def test_english_sample_is_read_and_has_no_errors(storage, sample):
    inv = storage.get_invoice(upload(storage, sample, S1))
    assert inv["status"] == "pending"
    assert (inv["vendor_name"], inv["invoice_number"], inv["invoice_date"]) == ("Demo Supplies W.L.L.", "INV-2026-0412", "2026-10-03")
    assert (inv["subtotal"], inv["vat_amount"], inv["total"]) == (450.0, 45.0, 495.0)
    assert codes(inv, "error") == []


def test_arabic_and_bilingual_pdf_samples(storage, sample):
    arabic = storage.get_invoice(upload(storage, sample, S2))
    assert arabic["vendor_name"] == "شركة العينة للكهرباء"
    assert arabic["total"] == 1320.0 and codes(arabic, "error") == []

    pdf = storage.get_invoice(upload(storage, sample, S5))
    assert pdf["stored_name"].endswith(".pdf") and codes(pdf, "error") == []


def test_wrong_total_is_flagged_and_needs_an_explicit_override(storage, sample):
    invoice_id = upload(storage, sample, S3)
    assert "sum_mismatch" in codes(storage.get_invoice(invoice_id), "error")

    with pytest.raises(service.ReviewError):
        service.approve(storage, invoice_id, "sara")
    assert storage.get_invoice(invoice_id)["status"] == "pending"

    service.approve(storage, invoice_id, "sara", override=True)
    assert storage.get_invoice(invoice_id)["status"] == "approved"
    approvals = [r for r in storage.list_audit() if r["action"] == "approve"]
    assert "WITH OVERRIDE" in approvals[0]["detail"] and "sum_mismatch" in approvals[0]["detail"]


def test_correcting_the_total_clears_the_error(storage, sample):
    invoice_id = upload(storage, sample, S3)
    inv = service.update_fields(storage, invoice_id, {"total": "330.000"}, "sara")
    assert codes(inv, "error") == []
    service.approve(storage, invoice_id, "sara")
    assert storage.get_invoice(invoice_id)["reviewed_by"] == "sara"
    edits = [r for r in storage.list_audit() if r["action"] == "edit"]
    assert "total" in edits[0]["detail"]


def test_invalid_amount_text_is_rejected(storage, sample):
    invoice_id = upload(storage, sample, S1)
    with pytest.raises(service.ReviewError):
        service.update_fields(storage, invoice_id, {"total": "ten"}, "sara")


def test_resent_invoice_is_caught_as_duplicate(storage, sample):
    upload(storage, sample, S1)
    dup = storage.get_invoice(upload(storage, sample, S4))
    assert "duplicate_invoice" in codes(dup, "error")


def test_same_file_twice_is_caught(storage, sample):
    upload(storage, sample, S1)
    again = storage.get_invoice(upload(storage, sample, S1))
    assert "duplicate_file" in codes(again, "error")


def test_rejecting_removes_the_duplicate_block(storage, sample):
    first = upload(storage, sample, S1)
    service.reject(storage, first, "sara")
    again = storage.get_invoice(upload(storage, sample, S1))
    assert "duplicate_file" not in codes(again)


def test_decided_invoices_cannot_be_changed(storage, sample):
    invoice_id = upload(storage, sample, S1)
    service.approve(storage, invoice_id, "sara")
    for action in (
        lambda: service.approve(storage, invoice_id, "sara"),
        lambda: service.reject(storage, invoice_id, "sara"),
        lambda: service.update_fields(storage, invoice_id, {"total": "1"}, "sara"),
    ):
        with pytest.raises(service.ReviewError):
            action()


def test_unknown_document_in_demo_mode_needs_manual_entry(storage, sample):
    data = sample(S1)
    inv = storage.get_invoice(service.process_upload(storage, "scan.png", data, "sara"))
    assert inv["vendor_name"] is None
    assert "missing_vendor_name" in codes(inv, "error") and "low_confidence" in codes(inv)


def test_non_invoice_files_are_refused(storage):
    for name, data in (("notes.txt", b"hello"), ("evil.png", b"MZ\x90\x00 not an image"), ("empty.pdf", b"")):
        with pytest.raises(service.UploadError):
            service.process_upload(storage, name, data, "sara")
    assert storage.list_invoices() == []


def test_oversize_file_is_refused(storage, sample, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 0)
    with pytest.raises(service.UploadError):
        upload(storage, sample, S1)


def test_file_type_comes_from_content_not_filename(storage, sample):
    invoice_id = service.process_upload(storage, "invoice.pdf", sample(S1), "sara")  # really a PNG
    assert storage.get_invoice(invoice_id)["stored_name"].endswith(".png")


def test_uploaded_filename_never_controls_the_storage_path(storage, sample):
    invoice_id = service.process_upload(storage, "../../etc/cron.d/evil.png", sample(S1), "sara")
    inv = storage.get_invoice(invoice_id)
    assert inv["filename"] == "evil.png"
    assert "/" not in inv["stored_name"] and storage.file_path(inv).parent == storage.upload_dir
    assert service.safe_filename("C:\\Users\\x\\a.png") == "a.png"


def test_failed_reading_leaves_nothing_behind_and_is_logged(storage, sample):
    def broken(path, name):
        raise RuntimeError("api down")

    with pytest.raises(RuntimeError):
        service.process_upload(storage, S1, sample(S1), "sara", extractor=broken)
    assert list(storage.upload_dir.iterdir()) == []
    assert storage.list_invoices() == []
    assert any(r["action"] == "extract_failed" for r in storage.list_audit())
