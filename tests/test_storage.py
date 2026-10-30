from datetime import datetime, timedelta, timezone

from marf import service


def old(storage, invoice_id, days=200):
    when = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with storage._conn() as conn:
        conn.execute("UPDATE invoices SET uploaded_at = ? WHERE id = ?", (when, invoice_id))


def test_purge_removes_old_files_but_keeps_the_data(storage, sample):
    invoice_id = service.process_upload(storage, "inv_01_demo_supplies_en.png", sample("inv_01_demo_supplies_en.png"), "sara")
    service.approve(storage, invoice_id, "sara")
    old(storage, invoice_id)
    path = storage.file_path(storage.get_invoice(invoice_id))

    assert storage.purge_old_files(90) == 1
    assert not path.exists()
    inv = storage.get_invoice(invoice_id)
    assert inv["stored_name"] is None and inv["total"] == 495.0 and storage.file_path(inv) is None


def test_purge_never_touches_pending_or_recent_files(storage, sample):
    pending = service.process_upload(storage, "inv_01_demo_supplies_en.png", sample("inv_01_demo_supplies_en.png"), "sara")
    old(storage, pending)
    assert storage.purge_old_files(90) == 0  # still waiting for review

    recent = service.process_upload(storage, "inv_02_arabic_electrical_ar.png", sample("inv_02_arabic_electrical_ar.png"), "sara")
    service.approve(storage, recent, "sara")
    assert storage.purge_old_files(90) == 0  # not old enough


def test_shared_file_is_kept_while_a_newer_invoice_uses_it(storage, sample):
    name = "inv_01_demo_supplies_en.png"
    first = service.process_upload(storage, name, sample(name), "sara")
    second = service.process_upload(storage, name, sample(name), "sara")  # same bytes, same stored file
    service.reject(storage, first, "sara")
    service.reject(storage, second, "sara")
    old(storage, first)
    assert storage.purge_old_files(90) == 0
    assert storage.file_path(storage.get_invoice(second)) is not None


def test_file_path_refuses_to_leave_the_upload_folder(storage):
    assert storage.file_path({"stored_name": "../marf.db"}) is None
    assert storage.file_path({"stored_name": None}) is None


def test_audit_log_is_newest_first(storage):
    storage.log("sara", "one")
    storage.log("sara", "two")
    assert [r["action"] for r in storage.list_audit()] == ["two", "one"]
