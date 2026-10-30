# MARF

AI-assisted invoice processing for a small accounting office, with a person approving every entry.

The accountant drops in invoices (PDF or photo, Arabic or English). Claude reads them, plain code checks the numbers, and she reviews, corrects and approves. Approved invoices export to Excel. Nothing is added to the books without her sign-off.

> **Status: pilot / demo.** Built to prove the idea to a business owner. Read [Before using real company data](#before-using-real-company-data) before pointing it at anything real.

## How it works

```
 invoice file ──► Claude reads it ──► code checks it ──► person reviews ──► Excel
 (PDF/PNG/JPG)    (structured JSON)   (math, VAT,         (edit, approve,    (approved
                                       duplicates, dates)  reject)            rows only)
                                                              │
                                                              └──► audit log of everything
```

The AI only reads. The checks that decide whether something looks wrong are ordinary deterministic code (`marf/validate.py`), so they are predictable and tested.

| Check | Severity |
|---|---|
| Subtotal + VAT does not equal total | error |
| Missing vendor, number, date or total | error |
| Same file uploaded twice, or same vendor + invoice number | error |
| Same vendor + date + total with a different number | warning |
| VAT is not the expected percentage of the subtotal | warning |
| Total is over 3x the vendor's average (needs 3 approved invoices) | warning |
| Reader unsure (confidence under 80%), unusual currency, odd date | warning |

Errors block approval unless the person ticks a box saying they checked the invoice themselves. That override is written to the audit log.

## Quick start (demo mode, no API key)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/create_user.py sara --role admin      # asks for a password
streamlit run app.py
```

There are no default accounts. You create the first user yourself.

**Demo mode does not read anything.** Without an API key the app only recognises the five bundled sample files by filename and returns the answers stored in `samples/expected.json`. The sidebar says `DEMO MODE`. It is useful for developing and for a quick look at the screens. For a real demonstration to the owner, use live mode.

## Live mode

```bash
cp .env.example .env        # then put your key in .env
```

Set `ANTHROPIC_API_KEY`. The sidebar changes to `Live mode` and uploads are sent to the Claude API. For the pilot, create the API account in the client's company name, not a personal one, so billing and data terms belong to the business. Check current pricing and data-handling terms on Anthropic's site.

## Five-minute demo with the samples

All sample invoices are fictional and marked as samples. Upload everything in `samples/` and walk through:

1. `inv_01` is clean. All checks pass.
2. `inv_02` is Arabic, right-to-left. The vendor and numbers are read correctly.
3. `inv_03` has a **wrong printed total** (350.000 where the lines add to 330.000). It is flagged red and cannot be approved until fixed or overridden.
4. `inv_04` is **the same invoice as #1 sent again** as a different file. Flagged as a duplicate.
5. `inv_05` is a bilingual PDF.

Then fix #3's total, approve it, open the Export tab for the Excel file, and show the Audit tab (admin only).

## Security design

Built in:

- **Passwords:** scrypt with a per-user salt, minimum 10 characters, no default accounts.
- **Login:** 5 failed attempts lock the account for 10 minutes. Every failure shows the same message, so usernames cannot be probed.
- **Sessions:** signed out after 30 minutes of inactivity.
- **Uploads:** file type is decided from the file's bytes, not its name. Size is capped. Files are stored under their SHA-256 hash, so an uploaded filename can never choose a path.
- **Untrusted documents:** an invoice is treated as data. The prompt tells the model to ignore instructions printed on a document, the reply is forced through a fixed schema and coerced to safe types, nothing is auto-approved, text from invoices is escaped in the UI, and Excel cells are forced to plain text so a vendor named `=HYPERLINK(...)` can never run as a formula.
- **Human in the loop:** every invoice needs a person's approval. Overrides are logged.
- **Audit log:** sign-ins, failed attempts, uploads, every field edit (old to new), approvals, overrides, exports and file purges.
- **Secrets:** the API key lives only in the server's environment. `.env` and `data/` are in `.gitignore`.
- **Retention:** admins can delete original files older than N days while keeping the extracted data and the log.

Not built yet:

- HTTPS. Put the app behind a reverse proxy such as Caddy or nginx.
- Encryption at rest. Use full-disk encryption on the host (BitLocker, LUKS).
- Backups of `data/`.
- Two-factor sign-in or single sign-on.
- Separation of duties (the person who uploads cannot also approve).
- A tamper-proof audit log. Today it is append-only by convention; someone with access to the database file could alter it.

## Configuration

Set in `.env` or the environment. See `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | empty | Empty means demo mode |
| `MARF_MODEL` | `claude-sonnet-5-5` | Model used to read invoices |
| `MARF_CURRENCY` | `BHD` | Expected currency (others are flagged) |
| `MARF_VAT_RATE` | `0.10` | Expected VAT rate. Confirm the current rate before relying on it |
| `MARF_DATA_DIR` | `data` | Database and uploaded files |
| `MARF_MAX_UPLOAD_MB` | `10` | Largest accepted file |
| `MARF_RETENTION_DAYS` | `90` | Age at which originals can be purged |
| `MARF_SESSION_MINUTES` | `30` | Inactivity timeout |

## Project layout

```
app.py                 Streamlit web app (login, review, history, export, audit)
marf/extract.py        Claude API call and demo-mode reader
marf/validate.py       The checks (pure functions, no AI)
marf/service.py        Upload, edit, approve, reject
marf/storage.py        SQLite: users, invoices, audit log
marf/auth.py           Password hashing, login, lockout
marf/export.py         Excel export
scripts/create_user.py Create a user
scripts/make_samples.py Regenerate the sample invoices
samples/               Fictional invoices and expected.json
tests/                 pytest suite
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite runs offline. Live-mode tests stub the network, so they check what MARF sends and how it handles replies, not that the real service accepts the request.

## Before using real company data

- Run one live test with dummy invoices and your own key before showing it to anyone. Live mode has only been exercised against a stubbed API so far.
- Compare the reader's output against the accountant's own entries on a few dozen real invoices and record the error rate. That number is your pilot result.
- Put HTTPS, disk encryption and backups in place.
- Check Anthropic's current commercial and data-retention terms, and Bahrain's personal data protection requirements, with the business's legal adviser. Invoices can contain personal details.
- Confirm the VAT rate and the invoice formats the office actually receives (including handwritten or low-quality scans).
- Agree who the users are and who can approve.

## Ideas for later

Rent and service-charge invoice generation, payment reminders, bank-statement matching, a monthly summary for the owner, a mobile-friendly capture page, and direct export to whatever accounting software the office uses once you know what it is.
