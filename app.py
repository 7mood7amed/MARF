"""MARF web app. Run with:  streamlit run app.py"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import streamlit as st

from marf import auth, config, service
from marf.export import build_workbook
from marf.storage import Storage
from marf.validate import FIELD_LABELS

st.set_page_config(page_title="MARF", page_icon="🧾", layout="wide")


@st.cache_resource
def get_storage() -> Storage:
    config.ensure_dirs()
    return Storage(config.DB_PATH, config.UPLOAD_DIR)


storage = get_storage()


def esc(text) -> str:
    """Escape Markdown so text read from an invoice can't turn into links or formatting."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|~<>$:&])", r"\\\1", str(text or ""))


def flash(kind: str, message: str) -> None:
    st.session_state.setdefault("flash", []).append((kind, message))


def show_flash() -> None:
    for kind, message in st.session_state.pop("flash", []):
        getattr(st, kind)(message)


def current_user() -> dict | None:
    user = st.session_state.get("user")
    if not user:
        return None
    now = datetime.now(timezone.utc)
    if now - st.session_state.get("last_active", now) > timedelta(minutes=config.SESSION_MINUTES):
        storage.log(user["username"], "session_timeout")
        st.session_state.clear()
        flash("info", "You were signed out after a period of inactivity.")
        return None
    st.session_state["last_active"] = now
    return user


def login_view() -> None:
    st.title("MARF")
    st.caption("Invoice processing with a person in the loop")
    show_flash()
    if storage.count_users() == 0:
        st.warning("No users exist yet. Create one in the terminal:  `python scripts/create_user.py <username> --role admin`")
        return
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        user, message = auth.authenticate(storage, username.strip(), password)
        if user:
            st.session_state.update(user=user, last_active=datetime.now(timezone.utc))
            st.rerun()
        st.error(message)


def sidebar(user: dict) -> None:
    with st.sidebar:
        st.title("MARF")
        st.write(f"Signed in as **{user['username']}** ({user['role']})")
        if config.live_mode():
            st.success(f"Live mode · model `{config.MODEL}`")
        else:
            st.warning("DEMO MODE: no API key. Only the bundled sample invoices can be read.")
        if st.button("Sign out"):
            storage.log(user["username"], "logout")
            st.session_state.clear()
            st.rerun()


def amount_text(value) -> str:
    return "" if value is None else f"{value:.3f}"


def review_card(inv: dict, user: dict, position: int) -> None:
    flags = inv["flags"]
    has_errors = any(f["severity"] == "error" for f in flags)
    icon = "🔴" if has_errors else "🟡" if flags else "🟢"
    label = f"{icon} #{inv['id']} · {esc(inv['vendor_name'] or 'Unknown vendor')} · {esc(inv['invoice_number'] or 'no number')}"
    key = inv["id"]

    with st.expander(label, expanded=position < 3):
        left, right = st.columns([1, 1.4])
        with left:
            path = storage.file_path(inv)
            if path is None:
                st.caption("Original file is no longer stored.")
            elif path.suffix == ".pdf":
                st.caption(f"PDF: {esc(inv['filename'])}")
                st.download_button("Download original", path.read_bytes(), file_name=inv["filename"], key=f"dl_{key}")
            else:
                st.image(str(path))
        with right:
            for flag in flags:
                (st.error if flag["severity"] == "error" else st.warning)(flag["message"])
            if inv["notes"]:
                st.info(f"Reader's note: {esc(inv['notes'])}")
            if not flags:
                st.success("All automatic checks passed. Please still compare against the original.")

            with st.form(f"form_{key}"):
                vendor = st.text_input(FIELD_LABELS["vendor_name"], inv["vendor_name"] or "", key=f"vendor_{key}")
                c1, c2 = st.columns(2)
                number = c1.text_input(FIELD_LABELS["invoice_number"], inv["invoice_number"] or "", key=f"number_{key}")
                inv_date = c2.text_input("Invoice date (YYYY-MM-DD)", inv["invoice_date"] or "", key=f"date_{key}")
                c3, c4, c5, c6 = st.columns(4)
                currency = c3.text_input(FIELD_LABELS["currency"], inv["currency"] or "", key=f"cur_{key}")
                subtotal = c4.text_input(FIELD_LABELS["subtotal"], amount_text(inv["subtotal"]), key=f"sub_{key}")
                vat = c5.text_input(FIELD_LABELS["vat_amount"], amount_text(inv["vat_amount"]), key=f"vat_{key}")
                total = c6.text_input(FIELD_LABELS["total"], amount_text(inv["total"]), key=f"tot_{key}")
                override = False
                if has_errors:
                    override = st.checkbox(
                        "I checked this invoice myself and it is correct. Approve it despite the errors above.",
                        key=f"override_{key}",
                    )
                b1, b2, b3 = st.columns(3)
                save = b1.form_submit_button("Save & re-check")
                approve = b2.form_submit_button("Approve", type="primary")
                reject = b3.form_submit_button("Reject")

            if save or approve or reject:
                values = {
                    "vendor_name": vendor,
                    "invoice_number": number,
                    "invoice_date": inv_date,
                    "currency": currency,
                    "subtotal": subtotal,
                    "vat_amount": vat,
                    "total": total,
                }
                try:
                    if reject:
                        service.reject(storage, key, user["username"])
                        flash("info", f"Invoice #{key} rejected.")
                    else:
                        service.update_fields(storage, key, values, user["username"])
                        if approve:
                            service.approve(storage, key, user["username"], override=override)
                            flash("success", f"Invoice #{key} approved.")
                        else:
                            flash("info", f"Invoice #{key} saved and re-checked.")
                except service.ReviewError as exc:
                    flash("error", f"Invoice #{key}: {exc}")
                st.rerun()


def upload_tab(user: dict) -> None:
    uploader_key = f"uploader_{st.session_state.get('uploader_n', 0)}"
    files = st.file_uploader(
        "Drop invoices here (PDF, PNG, JPG or WEBP)",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key=uploader_key,
    )
    if files and st.button("Read invoices", type="primary"):
        for uploaded in files:
            try:
                with st.spinner(f"Reading {uploaded.name}..."):
                    invoice_id = service.process_upload(storage, uploaded.name, uploaded.getvalue(), user["username"])
                flash("success", f"{esc(uploaded.name)} was read as invoice #{invoice_id}. Check it below.")
            except service.UploadError as exc:
                flash("error", f"{esc(uploaded.name)}: {exc}")
            except Exception as exc:  # noqa: BLE001
                flash("error", f"{esc(uploaded.name)} could not be read ({type(exc).__name__}). Try again or enter it by hand.")
        st.session_state["uploader_n"] = st.session_state.get("uploader_n", 0) + 1
        st.rerun()

    pending = storage.list_invoices(status="pending")
    st.subheader(f"Waiting for review ({len(pending)})")
    if not pending:
        st.caption("Nothing to review. Upload an invoice above.")
    for position, inv in enumerate(pending):
        review_card(inv, user, position)


def history_tab() -> None:
    status = st.selectbox("Show", ["all", "pending", "approved", "rejected"])
    rows = storage.list_invoices(None if status == "all" else status)
    if not rows:
        st.caption("No invoices yet.")
        return
    st.dataframe(
        [
            {
                "ID": r["id"],
                "Status": r["status"],
                "Vendor": r["vendor_name"],
                "Invoice #": r["invoice_number"],
                "Date": r["invoice_date"],
                "Currency": r["currency"],
                "Subtotal": r["subtotal"],
                "VAT": r["vat_amount"],
                "Total": r["total"],
                "Flags": ", ".join(f["code"] for f in r["flags"]),
                "Uploaded by": r["uploaded_by"],
                "Reviewed by": r["reviewed_by"],
            }
            for r in rows
        ],
        hide_index=True,
    )


def export_tab(user: dict) -> None:
    approved = storage.list_invoices(status="approved")
    st.write(f"**{len(approved)}** approved invoice(s) ready to export. Only approved invoices are included.")
    if approved:
        st.download_button(
            "Download Excel file",
            build_workbook(approved),
            file_name=f"marf-export-{date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            on_click=lambda: storage.log(user["username"], "export", f"{len(approved)} invoices"),
        )


def admin_tab(user: dict) -> None:
    st.subheader("Audit log")
    st.caption("Newest first. Every upload, edit, approval, override, export and sign-in is recorded here.")
    rows = storage.list_audit(500)
    if rows:
        st.dataframe(rows, hide_index=True)
    else:
        st.caption("No events yet.")

    st.subheader("Data retention")
    st.write(
        f"Original invoice files are kept for {config.RETENTION_DAYS} days. "
        "Deleting them keeps the extracted data and the audit log."
    )
    if st.button(f"Delete original files older than {config.RETENTION_DAYS} days"):
        removed = storage.purge_old_files(config.RETENTION_DAYS)
        storage.log(user["username"], "purge_files", f"{removed} files removed")
        flash("success", f"{removed} original file(s) deleted.")
        st.rerun()


user = current_user()
if user is None:
    login_view()
    st.stop()

sidebar(user)
show_flash()

tab_names = ["Upload & review", "History", "Export"] + (["Audit & data"] if user["role"] == "admin" else [])
tabs = st.tabs(tab_names)
with tabs[0]:
    upload_tab(user)
with tabs[1]:
    history_tab()
with tabs[2]:
    export_tab(user)
if user["role"] == "admin":
    with tabs[3]:
        admin_tab(user)
