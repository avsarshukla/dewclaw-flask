
Project Report

## Project Overview
Dewclaw is a lightweight, full-stack web application designed to connect animal shelters with potential adopters. Unlike complex, bloated platforms that require heavy infrastructure, Dewclaw focuses on a streamlined, single-shelter workflow. It provides a clear pipeline for dogs—from intake and listing to reservation and adoption—while maintaining a transparent history of every dog's journey. 

The project is deployed as a live MVP using a free-tier cloud architecture.

## 1. Core Features

The platform operates on a two-role model: **Adopter** and **Shelter Admin**. Every feature below is implemented and functional in the deployed MVP.

### 1.1 Authentication and Roles

- Session-based login using Flask-Login with hashed passwords (Werkzeug `generate_password_hash` / `check_password_hash`).
- Two roles enforced at the route level: `adopter` and `shelter_admin`.
- Adopter self-registration; admin account seeded on first boot.
- Decorator-based access control (`@admin_required`) prevents non-admin access to shelter routes.

### 1.2 Dog Management (Shelter Admin)

- Create, edit, and archive dog profiles with: name, breed, age, sex, temperament, health flags, description, and photo.
- Photo upload handled via `werkzeug.utils.secure_filename`, stored under `static/uploads/`.
- Status transitions: `available` → `reserved` → `adopted`.
- No hard delete — records persist for historical continuity.

### 1.3 Adoption Applications

- Adopters browse available dogs, view detail pages, and submit an application with a message.
- One application per (dog, adopter) pair, enforced by a database `UNIQUE` constraint rather than application logic.
- Adopters track application status (`pending`, `rejected`) from a personal dashboard.
- Shelter admin reviews pending applications and rejects with a written reason, which the adopter sees.

### 1.4 Reservation with Automatic Expiry

- Admin reserves a dog for 14 days; the dog locks for other applicants.
- Expiry is evaluated lazily on read — no background job required (see §3.1).
- Admin can unreserve or convert a reservation to adoption at any time.

### 1.5 Activity Timeline

- Every state change writes an immutable row to an `activity` table: added to shelter, application submitted, reserved until [date], reservation cancelled, adopted.
- Timeline is publicly visible on each dog's detail page, providing transparency for adopters and an audit trail for the shelter.

### 1.6 Shelter Dashboard

- Single view consolidating: pending applications, active reservations, and all dogs with status and available actions.
- Actions available inline: reject application with reason, reserve, unreserve, adopt, edit.

---

## 2. Tech Stack and Delivery

The architecture was intentionally constrained to a **single-file Flask monolith with zero external services**. Every layer was chosen to minimise moving parts, not to demonstrate breadth.

| Layer | Technology | Rationale |
|---|---|---|
| **Application** | Flask 3.0.3 | Minimal, unopinionated framework; one file can hold the entire app |
| **Database** | SQLite (stdlib `sqlite3`) | File-based, serverless, zero configuration; persists on PythonAnywhere's disk |
| **Templating** | Jinja2 via `DictLoader` | Templates registered as strings in `app.py`; no `templates/` directory |
| **Authentication** | Flask-Login + Werkzeug | Session cookies instead of JWT; no client-side token storage |
| **Password Hashing** | Werkzeug `generate_password_hash` | Ships with Flask; no extra dependency |
| **File Uploads** | `werkzeug.utils.secure_filename` | Built into Flask's dependency tree; no `multer` equivalent needed |
| **Hosting** | PythonAnywhere (free tier) | Persistent SQLite; no ephemeral-storage workaround required |
| **Version Control** | Git + GitHub (public repo) | Deployment pull source; `git pull` + Reload is the entire redeploy loop |

**Deliberate exclusions.** No Docker. No Redis. No Celery. No background job queue. No separate frontend. No CORS. No JWT. No ORM. No migration framework. No CDN dependency for styling. No external database server.

**Resulting footprint.** Three tracked files (`app.py`, `requirements.txt`, `wsgi.py`), one static directory, one SQLite file created at runtime, three pinned dependencies.

---

## 3. Key Technical Innovations (Simplified Architecture)

Two design decisions replace conventional infrastructure with mechanisms internal to the application, and a third eliminates structural overhead. Each addresses a specific scaling or operational concern without introducing a new component.

### 3.1 Lazy Reservation Expiry — No Background Scheduler

**Conventional approach.** A cron job or task queue (Celery, RQ, APScheduler) periodically scans reservations and flips expired ones back to available.

**Dewclaw approach.** No scheduler exists. The function `effective_dog()` is invoked on every read of a dog record. It checks whether `status = 'reserved'` and `reserved_until < now()`; if so, it returns a view of the record with `status = 'available'` and `reserved_until = None`. No write-back occurs. The stale timestamp remains in the database until the next reservation overwrites it.

**Consequence.**
- Zero background workers, zero cron configuration, zero queue infrastructure.
- Correctness is guaranteed by evaluation time, not by scheduler reliability.
- The approach is only viable because the system is **read-mostly** and expiry is **idempotent** — a property that holds for a single-shelter workflow.

### 3.2 Activity Logging Without Event Sourcing

**Conventional approach.** Full event sourcing with an event store, projections, and read-model rebuilds.

**Dewclaw approach.** A single `activity` table with columns `(id, dog_id, event_type, message, created_at)`. Each state-changing action inserts one row inside the same transaction as the state change itself. The detail page renders rows in reverse chronological order.

**Consequence.**
- Transparent, human-readable history for adopters, in approximately five lines of insertion code per action.
- Full audit trail for the shelter, without projections or replay infrastructure.
- Sufficient for the stated requirement (verifiable history); insufficient for temporal queries, which the spec does not require.

### 3.3 Single-File Application via `DictLoader`

**Conventional approach.** Flask projects use `templates/` directories, blueprints, and separate `models.py` / `forms.py` / `views.py` modules.

**Dewclaw approach.** All Jinja templates are defined as module-level strings in `app.py` and registered with `jinja2.DictLoader`. All routes live in one file. `{% extends 'base' %}` resolves through the loader, so template inheritance survives without a filesystem.

**Consequence.**
- The entire application is one reviewable, deployable file.
- Zero import graph, zero circular dependency risk, zero directory-navigation overhead for a project of this scope.
- Trade-off accepted: no editor syntax highlighting inside templates, and the file is not suitable for team parallel development.

### 3.4 Database-Enforced Invariants

Business rules that are conventionally enforced in application code are instead enforced by schema constraints:

| Rule | Enforced by |
|---|---|
| One application per (dog, adopter) | `UNIQUE(dog_id, adopter_id)` on `applications` |
| Valid status values only | `CHECK(status IN (...))` on `dogs.status` and `applications.status` |
| No orphaned activity | `FOREIGN KEY (dog_id) REFERENCES dogs(id)` with `PRAGMA foreign_keys = ON` |

This means a bug in a route handler cannot violate the rule — the insert fails at the database.

---

## 4. Innovativeness

### 4.1 The Traditional Adoption Workflow

Current practice at small shelters and rescues:

| Stage | Tool used | Consequence |
|---|---|---|
| Discovery | Instagram posts, Facebook groups, WhatsApp forwards | Listing disappears from feed within hours; no searchable catalogue |
| Inquiry | WhatsApp DM or Instagram comment | No record; multiple volunteers may respond to the same person |
| Application | Free-text message | No structured data, no comparison across applicants |
| Coordination | WhatsApp group chat | Multiple adopters told "yes" for the same dog; race condition resolved manually and often too late |
| Handover | Verbal | No record of which adopter received which dog |
| Post-adoption | None | Dog's history after adoption is permanently lost |

**Fundamental limitation.** Social media provides *reach* but no *state*. WhatsApp provides *conversation* but no *record*. Neither provides a persistent, queryable object representing the dog, and neither enforces any invariant — the "two adopters told yes" failure is not an edge case, it is the expected outcome of the medium.

### 4.2 What Dewclaw Provides Instead

Dewclaw replaces **discovery + coordination** with an **end-to-end transactional pipeline** in which the dog record is the primary entity and every state change is persisted.

| Capability | Traditional workflow | Dewclaw |
|---|---|---|
| Searchable catalogue | Ephemeral social feed | Persistent, filterable listings |
| Application structure | Free-text DM | Structured application linked to dog and adopter |
| Double-adoption race | Resolved manually, often incorrectly | Prevented by database constraint and 14-day hold |
| Reservation expiry | Tracked mentally | Evaluated on read; no manual check required |
| Rejection feedback | Adopter ignored or ghosted | Written reason surfaced to adopter |
| Dog history | Lost after handover | Append-only timeline, publicly visible |
| Record deletion | Post removed, history gone | No delete path; records persist by design |
| Audit trail | None | Every state change logged with timestamp |

# Installation and Local Execution 

## Prerequisites

**P1.** Open Git Bash.

**P2.** Verify Python:
```bash
python --version
```
Expected: `Python 3.10.x` or higher.

**P3.** Verify pip:
```bash
python -m pip --version
```

**P4.** Verify Git:
```bash
git --version
```

**P5.** If `python --version` returns `Python was not found; run without arguments to install from the Microsoft Store`, use:
```bash
~/anaconda3/python.exe --version
```
Substitute `~/anaconda3/python.exe` for `python` in all following steps.

---

## Step 1 — Clone repository

```bash
cd ~
git clone https://github.com/avsarshukla/dewclaw-flask.git
cd dewclaw-flask
ls
```
Expected:
```
app.py  requirements.txt  wsgi.py  static/  .gitignore
```

---

## Step 2 — Create virtual environment

```bash
python -m venv venv
```
Wait 5–15 seconds for prompt to return. Do not press `Ctrl+C`.

If interrupted:
```bash
rm -rf venv
python -m venv venv
```

---

## Step 3 — Activate virtual environment

```bash
source venv/Scripts/activate
```
Expected prompt prefix:
```
(venv) ...
```

On Linux/macOS use:
```bash
source venv/bin/activate
```

---

## Step 4 — Install dependencies

```bash
pip install -r requirements.txt
```
Expected final line:
```
Successfully installed Flask-3.0.3 Flask-Login-0.6.3 Jinja2-3.1.6 MarkupSafe-3.0.4 Werkzeug-3.0.3 blinker-1.9.0 click-8.5.1 itsdangerous-2.2.0
```

Verify:
```bash
python -c "import flask; print(flask.__version__)"
```
Expected: `3.0.3`

---

## Step 5 — Launch application

```bash
python app.py
```
Expected:
```
 * Serving Flask app 'app'
 * Debug mode: on
 * Running on http://127.0.0.1:8000
Press CTRL+C to quit
```
Do not press `Ctrl+C`. Do not type in this terminal.

If output shows `port=5000`, edit last line of `app.py`:
```python
app.run(debug=True, port=8000)
```
Save and re-run.

---

## Step 6 — Open browser

Navigate to:
```
http://127.0.0.1:8000
```

---

## Step 7 — Verify

**V1.** Home page shows three dogs: Buddy, Luna, Max.

**V2.** Log in:
```
Email:    admin@dewclaw.local
Password: admin123
```

**V3.** Navigate to:
```
http://127.0.0.1:8000/admin
```
Dashboard loads.

**V4.** Click any dog → **Reserve 14d** → status shows Reserved with date.

**V5.** Click **Adopt** → status shows Adopted → timeline gains entry.

**V6.** Register new adopter in separate browser session.

**V7.** Submit application as adopter → visible in admin pending list.

---

## Step 8 — Stop server

Click Flask terminal, press `Ctrl+C`.

---

## Troubleshooting

**T1.** `Python was not found; run without arguments to install from the Microsoft Store`
→ Use `python`, not `python3`. Or use `~/anaconda3/python.exe`.

**T2.** `bash: venv/Scripts/activate: No such file or directory`
→ Run:
```bash
rm -rf venv
python -m venv venv
```

**T3.** `bash: venv/bin/activate: No such file or directory`
→ On Windows use:
```bash
source venv/Scripts/activate
```

**T4.** `pip: command not found`
→ Run Step 3 first. Or:
```bash
venv/Scripts/python.exe -m pip install -r requirements.txt
```

**T5.** Browser: `ERR_CONNECTION_REFUSED`
→ Verify Flask still running. In second Git Bash window:
```bash
netstat -ano | findstr :8000
```
Expected: line ending in `LISTENING`.

**T6.** `netstat` returns nothing
→ Flask not running. Re-run Step 5. Check terminal for traceback above `Running on`.

**T7.** All ports refused
→ Disable proxy: Windows Settings → Network & Internet → Proxy → turn off.
→ Disconnect VPN.
→ Disable antivirus web shield.

**T8.** `ModuleNotFoundError: No module named 'flask'`
→ Verify:
```bash
which python
```
Expected path contains `venv/Scripts/`.

---

## Linux deployment substitutions

| Windows | Linux |
|---|---|
| `python` | `python3` |
| `venv/Scripts/activate` | `venv/bin/activate` |
| `python app.py` | not used — served by WSGI |

---

## Demo — Change color and font

**D1.** Open `app.py` in editor.

**D2.** Search `TWEAK COLORS + FONTS HERE`.

**D3.** Change primary color:
```css
  --primary:   #2563eb;
```
to:
```css
  --primary:   #c026d3;
```

**D4.** Save (`Ctrl+S`).

**D5.** Wait for terminal output:
```
 * Detected change in 'app.py', reloading
```

**D6.** Refresh browser. Buttons and links change color.

**D7.** Change nav bar:
```css
  --nav-bg:    #111827;
```
to:
```css
  --nav-bg:    #7c2d12;
```

**D8.** Save and refresh.

**D9.** Change font:
```css
  --font-body:    system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
```
to:
```css
  --font-body:    Georgia, "Times New Roman", serif;
```

**D10.** Save and refresh. Site switches to serif.

**D11.** Revert all three values to originals. Save and refresh.

**D12.** If auto-reload fails: press `Ctrl+C` in Flask terminal, re-run `python app.py`, refresh browser.

**D13.** Auto-reload applies to local server only. PythonAnywhere requires `git pull` + **Reload** button.
