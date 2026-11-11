"""Dewclaw — single-file Flask + SQLite pet adoption MVP."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    Flask, abort, flash, redirect, render_template, request, url_for,
)
from flask_login import (
    LoginManager, UserMixin, current_user, login_required,
    login_user, logout_user,
)
from jinja2 import DictLoader
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------- config

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
    UPLOAD_FOLDER=os.path.join(app.root_path, "static", "uploads"),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("HTTPS") == "1",
    REMEMBER_COOKIE_SECURE=os.environ.get("HTTPS") == "1",
    REMEMBER_COOKIE_HTTPONLY=True,
)
DB_PATH = os.environ.get(
    "DATABASE_PATH",
    os.path.join(app.root_path, "dewclaw.db"),
)
RESERVATION_DAYS = 14
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ---------------------------------------------------------------- helpers


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(s):
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def effective_dog(row):
    """Lazy expiry: reserved with past reserved_until reads as available."""
    if row is None:
        return None
    d = dict(row)
    if d["status"] == "reserved" and d.get("reserved_until"):
        if parse_iso(d["reserved_until"]) < datetime.now(timezone.utc):
            d["status"] = "available"
            d["reserved_until"] = None
    return d


def log_activity(conn, dog_id, event_type, message):
    conn.execute(
        "INSERT INTO activity (dog_id, event_type, message, created_at) "
        "VALUES (?, ?, ?, ?)",
        (dog_id, event_type, message, now_iso()),
    )


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def parse_float(s):
    try:
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_photo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = secure_filename(f"{stamp}-{file_storage.filename}")
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return filename


# ---------------------------------------------------------------- schema

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('adopter','shelter_admin')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dogs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    breed TEXT DEFAULT '',
    age_years REAL,
    sex TEXT DEFAULT '',
    temperament TEXT DEFAULT '',
    health_flags TEXT DEFAULT '',
    description TEXT DEFAULT '',
    photo_filename TEXT,
    status TEXT NOT NULL DEFAULT 'available'
        CHECK(status IN ('available','reserved','adopted')),
    reserved_until TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dog_id INTEGER NOT NULL REFERENCES dogs(id) ON DELETE RESTRICT,
    adopter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    message TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','rejected')),
    rejection_reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(dog_id, adopter_id)
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dog_id INTEGER NOT NULL REFERENCES dogs(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_dog ON activity(dog_id, created_at);
CREATE INDEX IF NOT EXISTS idx_apps_dog ON applications(dog_id);
CREATE INDEX IF NOT EXISTS idx_apps_adopter ON applications(adopter_id);
"""


def init_db():
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def seed_demo_data():
    conn = get_db()
    try:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
            return
        conn.execute(
            "INSERT INTO users (email, password_hash, name, role, created_at) "
            "VALUES (?, ?, ?, 'shelter_admin', ?)",
            (
                "admin@dewclaw.local",
                generate_password_hash("admin123"),
                "Shelter Admin",
                now_iso(),
            ),
        )
        demo = [
            ("Buddy", "Labrador Mix", 3.5, "male", "Friendly, energetic",
             "Vaccinated", "Loves fetch and long walks. Good with kids."),
            ("Luna", "Husky", 2.0, "female", "Talkative, playful",
             "Vaccinated", "High energy. Needs an active household."),
            ("Max", "Beagle", 5.0, "male", "Calm, affectionate",
             "Vaccinated, neutered", "A gentle soul who loves naps and snacks."),
        ]
        for name, breed, age, sex, temp, health, desc in demo:
            cur = conn.execute(
                "INSERT INTO dogs (name, breed, age_years, sex, temperament, "
                "health_flags, description, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, breed, age, sex, temp, health, desc, now_iso()),
            )
            log_activity(conn, cur.lastrowid, "added", "Added to shelter.")
        conn.commit()
    finally:
        conn.close()


init_db()
seed_demo_data()

# ---------------------------------------------------------------- auth

class User(UserMixin):
    def __init__(self, row):
        self.id = str(row["id"])
        self.email = row["email"]
        self.name = row["name"]
        self.role = row["role"]

    @property
    def is_admin(self):
        return self.role == "shelter_admin"


login_manager = LoginManager(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()
    return User(row) if row else None


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------- templates

BASE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{% block title %}Dewclaw{% endblock %}</title>
<style>
/* ================================================================
   TWEAK COLORS + FONTS HERE. Everything below uses these variables.
   ================================================================ */
:root {
  --font-body:    system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-heading: var(--font-body);

  --bg:        #fafafa;
  --fg:        #222222;
  --muted:     #6b7280;
  --card-bg:   #ffffff;
  --border:    #e5e7eb;

  --primary:   #2563eb;
  --primary-fg:#ffffff;
  --success:   #16a34a;
  --warning:   #d97706;
  --danger:    #dc2626;
  --info:      #0891b2;

  --nav-bg:    #111827;
  --nav-fg:    #ffffff;

  --radius:    6px;
  --max-width: 1100px;
}
*{box-sizing:border-box}
body{margin:0;font-family:var(--font-body);background:var(--bg);color:var(--fg);line-height:1.5}
h1,h2,h3,h4{font-family:var(--font-heading);margin:0 0 .75rem}
a{color:var(--primary);text-decoration:none}
a:hover{text-decoration:underline}

.nav{background:var(--nav-bg);color:var(--nav-fg)}
.nav-inner{max-width:var(--max-width);margin:0 auto;padding:12px 16px;
  display:flex;align-items:center;gap:12px}
.nav-brand{color:var(--nav-fg);font-weight:600;font-size:1.1rem}
.nav-links{margin-left:auto;display:flex;gap:8px;align-items:center}
.nav-links .name{opacity:.75;font-size:.9rem;margin:0 6px}

.container{max-width:var(--max-width);margin:0 auto;padding:24px 16px 64px}

.btn{display:inline-block;padding:6px 12px;border-radius:var(--radius);
  border:1px solid var(--border);background:var(--card-bg);color:var(--fg);
  cursor:pointer;font:inherit;font-size:.9rem;line-height:1.2;text-decoration:none}
.btn:hover{background:#f3f4f6;text-decoration:none}
.btn-sm{padding:3px 8px;font-size:.8rem}
.btn-primary{background:var(--primary);border-color:var(--primary);color:var(--primary-fg)}
.btn-primary:hover{filter:brightness(.94)}
.btn-light{background:var(--nav-fg);border-color:var(--nav-fg);color:var(--nav-bg)}
.btn-outline-light{background:transparent;border-color:var(--nav-fg);color:var(--nav-fg)}
.btn-danger{color:var(--danger);border-color:var(--danger);background:#fff}
.btn-success{background:var(--success);border-color:var(--success);color:#fff}
.btn-warning{color:var(--warning);border-color:var(--warning);background:#fff}

.card{background:var(--card-bg);border:1px solid var(--border);
  border-radius:var(--radius);overflow:hidden;height:100%}
.card img{width:100%;height:200px;object-fit:cover;display:block}
.card-body{padding:12px 14px 14px}

.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}

.field{margin-bottom:12px}
.field label{display:block;font-size:.85rem;color:var(--muted);margin-bottom:4px}
input[type=text],input[type=email],input[type=password],input[type=number],
input[type=file],select,textarea{
  width:100%;padding:7px 9px;border:1px solid var(--border);
  border-radius:var(--radius);font:inherit;background:#fff;color:var(--fg)}
input:focus,select:focus,textarea:focus{
  outline:none;border-color:var(--primary);box-shadow:0 0 0 2px rgba(37,99,235,.15)}

.alert{padding:10px 14px;border-radius:var(--radius);margin-bottom:12px;
  border:1px solid var(--border);background:#fff}
.alert-success{border-color:var(--success);color:#166534;background:#f0fdf4}
.alert-error,.alert-danger{border-color:var(--danger);color:#991b1b;background:#fef2f2}
.alert-info{border-color:var(--info);color:#155e75;background:#ecfeff}
.alert-warning{border-color:var(--warning);color:#92400e;background:#fffbeb}

.badge{display:inline-block;padding:1px 8px;border-radius:999px;
  font-size:.75rem;font-weight:600}
.badge-available,.badge-success{background:#dcfce7;color:#166534}
.badge-reserved,.badge-warning{background:#fef3c7;color:#92400e}
.badge-adopted,.badge-primary{background:#dbeafe;color:#1e40af}
.badge-rejected,.badge-danger{background:#fee2e2;color:#991b1b}
.badge-pending,.badge-info{background:#cffafe;color:#155e75}

table{width:100%;border-collapse:collapse;background:var(--card-bg);
  border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:16px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);vertical-align:top}
th{background:#f9fafb;font-size:.78rem;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted)}
tr:last-child td{border-bottom:none}

.timeline{list-style:none;padding:0;margin:0}
.timeline li{padding:10px 0;border-bottom:1px solid var(--border)}
.timeline small{color:var(--muted)}

.muted{color:var(--muted)}
.small{font-size:.85rem}
.mb-2{margin-bottom:.5rem}.mb-3{margin-bottom:1rem}.mb-4{margin-bottom:1.5rem}
.mt-3{margin-top:1rem}.mt-4{margin-top:1.5rem}

.flex-between{display:flex;justify-content:space-between;align-items:center;
  gap:12px;flex-wrap:wrap}
.form-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.form-row input[type=text]{flex:2 1 200px}
.form-row select{flex:1 1 140px}
.form-narrow{max-width:420px;margin:0 auto}
.row-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:640px){.row-2{grid-template-columns:1fr}}
.detail-photo{width:100%;border-radius:var(--radius);display:block}
.no-photo{background:#e5e7eb;color:var(--muted);display:flex;align-items:center;
  justify-content:center;border-radius:var(--radius)}
.res-row{display:flex;justify-content:space-between;align-items:center;
  padding:8px 12px;border:1px solid var(--border);border-radius:var(--radius);
  background:var(--card-bg);margin-bottom:8px;gap:8px;flex-wrap:wrap}
</style></head><body>
<nav class="nav"><div class="nav-inner">
<a class="nav-brand" href="{{ url_for('index') }}">🐾 Dewclaw</a>
<div class="nav-links">
{% if current_user.is_authenticated %}
  {% if current_user.is_admin %}
    <a class="btn btn-sm btn-outline-light" href="{{ url_for('admin_dashboard') }}">Admin</a>
  {% else %}
    <a class="btn btn-sm btn-outline-light" href="{{ url_for('my_applications') }}">My Applications</a>
  {% endif %}
  <span class="name">{{ current_user.name }}</span>
  <form method="post" action="{{ url_for('logout') }}" style="margin:0">
    <button class="btn btn-sm btn-light">Log out</button>
  </form>
{% else %}
  <a class="btn btn-sm btn-outline-light" href="{{ url_for('login') }}">Log in</a>
  <a class="btn btn-sm btn-light" href="{{ url_for('register') }}">Register</a>
{% endif %}
</div></div></nav>
<main class="container">
{% with messages = get_flashed_messages(with_categories=true) %}
{% for category, message in messages %}
  <div class="alert alert-{{ category }}">{{ message }}</div>
{% endfor %}{% endwith %}
{% block content %}{% endblock %}
</main></body></html>"""


INDEX = """{% extends 'base' %}{% block content %}
<h1 class="mb-4">Adoptable Dogs</h1>
<form method="get" class="form-row mb-4">
  <input type="text" name="q" placeholder="Search name or breed"
         value="{{ request.args.get('q','') }}">
  <select name="status">
    <option value="available" {% if request.args.get('status','available') == 'available' %}selected{% endif %}>Available only</option>
    <option value="all" {% if request.args.get('status') == 'all' %}selected{% endif %}>All dogs</option>
  </select>
  <button class="btn btn-primary">Filter</button>
</form>
{% if not dogs %}<p class="muted">No dogs match your criteria.</p>{% endif %}
<div class="grid">{% for dog in dogs %}<div class="card">
  {% if dog['photo_filename'] %}
    <img src="{{ url_for('static', filename='uploads/' + dog['photo_filename']) }}" alt="{{ dog['name'] }}">
  {% else %}<div class="no-photo" style="height:200px">No photo</div>{% endif %}
  <div class="card-body">
    <h3 style="margin:0 0 .25rem">{{ dog['name'] }}</h3>
    <p class="mb-2" style="margin:0 0 .25rem">{{ dog['breed'] or 'Mixed breed' }}
      {% if dog['age_years'] %} · {{ dog['age_years'] }} yrs{% endif %}</p>
    <p class="muted small mb-3">{{ dog['temperament'] }}</p>
    <a class="btn" href="{{ url_for('dog_detail', dog_id=dog['id']) }}">View details</a>
  </div>
</div>{% endfor %}</div>
{% endblock %}"""


DETAIL = """{% extends 'base' %}{% block content %}
<a class="small" href="{{ url_for('index') }}">← Back to listings</a>
<div class="row-2 mt-3">
  <div>
    {% if dog['photo_filename'] %}
      <img class="detail-photo" src="{{ url_for('static', filename='uploads/' + dog['photo_filename']) }}" alt="{{ dog['name'] }}">
    {% else %}<div class="no-photo" style="height:400px">No photo</div>{% endif %}
  </div>
  <div>
    <h1 style="margin:0 0 .5rem">{{ dog['name'] }}
      {% if dog['status'] == 'available' %}<span class="badge badge-success">Available</span>
      {% elif dog['status'] == 'reserved' %}<span class="badge badge-warning">Reserved</span>
      {% elif dog['status'] == 'adopted' %}<span class="badge badge-primary">Adopted</span>{% endif %}
    </h1>
    <p style="margin:.25rem 0"><strong>Breed:</strong> {{ dog['breed'] or '—' }}</p>
    <p style="margin:.25rem 0"><strong>Age:</strong> {{ dog['age_years'] or '—' }} years</p>
    <p style="margin:.25rem 0"><strong>Sex:</strong> {{ dog['sex'] or '—' }}</p>
    <p style="margin:.25rem 0"><strong>Temperament:</strong> {{ dog['temperament'] or '—' }}</p>
    <p style="margin:.25rem 0"><strong>Health:</strong> {{ dog['health_flags'] or '—' }}</p>
    <p class="mt-3">{{ dog['description'] }}</p>
    {% if dog['status'] == 'reserved' and dog['reserved_until'] %}
      <p style="color:var(--warning)"><strong>Reserved until:</strong> {{ dog['reserved_until'][:10] }}</p>
    {% endif %}
    {% if my_app %}
      {% if my_app['status'] == 'rejected' %}
        <div class="alert alert-warning mt-3">Your application was not accepted.
          {% if my_app['rejection_reason'] %}<br><em>{{ my_app['rejection_reason'] }}</em>{% endif %}</div>
      {% else %}
        <div class="alert alert-info mt-3">You already applied for {{ dog['name'] }} (status: {{ my_app['status'] }}).</div>
      {% endif %}
    {% elif current_user.is_authenticated and not current_user.is_admin and dog['status'] == 'available' %}
      <form method="post" action="{{ url_for('apply', dog_id=dog['id']) }}" class="mt-3">
        <div class="field"><label>Message to shelter (optional)</label>
          <textarea name="message" rows="3" placeholder="Tell the shelter why you'd be a great match..."></textarea></div>
        <button class="btn btn-primary">Apply to adopt</button>
      </form>
    {% elif not current_user.is_authenticated and dog['status'] == 'available' %}
      <a class="btn btn-primary mt-3" href="{{ url_for('login') }}">Log in to apply</a>
    {% endif %}
  </div>
</div>
<h3 class="mt-4">Timeline</h3>
<ul class="timeline">
  {% for a in activities %}
    <li><strong>{{ a['message'] }}</strong><br>
      <small>{{ a['created_at'][:16].replace('T',' ') }}</small></li>
  {% else %}<li class="muted">No activity yet.</li>{% endfor %}
</ul>
{% endblock %}"""


LOGIN = """{% extends 'base' %}{% block content %}
<div class="form-narrow"><div class="card"><div class="card-body">
  <h2 class="mb-3">Log in</h2>
  <form method="post">
    <div class="field"><label>Email</label>
      <input type="email" name="email" required></div>
    <div class="field"><label>Password</label>
      <input type="password" name="password" required></div>
    <button class="btn btn-primary" style="width:100%">Log in</button>
  </form>
  <p class="small mt-3">No account? <a href="{{ url_for('register') }}">Register</a></p>
</div></div></div>
{% endblock %}"""


REGISTER = """{% extends 'base' %}{% block content %}
<div class="form-narrow"><div class="card"><div class="card-body">
  <h2 class="mb-3">Create adopter account</h2>
  <form method="post">
    <div class="field"><label>Name</label>
      <input type="text" name="name" required></div>
    <div class="field"><label>Email</label>
      <input type="email" name="email" required></div>
    <div class="field"><label>Password (min 6 chars)</label>
      <input type="password" name="password" minlength="6" required></div>
    <button class="btn btn-primary" style="width:100%">Register</button>
  </form>
  <p class="small mt-3">Already have an account? <a href="{{ url_for('login') }}">Log in</a></p>
</div></div></div>
{% endblock %}"""


MY_APPS = """{% extends 'base' %}{% block content %}
<h1 class="mb-4">My Applications</h1>
{% if not apps %}<p class="muted">You haven't applied for any dogs yet.
  <a href="{{ url_for('index') }}">Browse dogs</a>.</p>{% endif %}
<div class="grid">
{% for a in apps %}<div class="card"><div class="card-body">
  <h3 style="margin:0 0 .5rem">
    <a href="{{ url_for('dog_detail', dog_id=a['dog_id']) }}">{{ a['dog_name'] }}</a>
    <span class="badge badge-{{ a['dog_status'] }}">{{ a['dog_status'] }}</span>
  </h3>
  <p class="mb-2">Application:
    <span class="badge badge-{{ a['status'] }}">{{ a['status'] }}</span></p>
  <p class="muted small" style="margin:.25rem 0">Submitted {{ a['created_at'][:16].replace('T',' ') }}</p>
  {% if a['rejection_reason'] %}<p class="small"><em>Reason: {{ a['rejection_reason'] }}</em></p>{% endif %}
</div></div>{% endfor %}
</div>
{% endblock %}"""


ADMIN = """{% extends 'base' %}{% block content %}
<div class="flex-between mb-4">
  <h1 style="margin:0">Shelter Dashboard</h1>
  <a class="btn btn-primary" href="{{ url_for('admin_new_dog') }}">+ Add Dog</a>
</div>
<h3 class="mt-3">Pending Applications ({{ apps|length }})</h3>
{% if apps %}
<table><thead><tr><th>Dog</th><th>Adopter</th><th>Message</th><th>Submitted</th><th></th></tr></thead><tbody>
{% for a in apps %}<tr>
  <td><a href="{{ url_for('dog_detail', dog_id=a['dog_id']) }}">{{ a['dog_name'] }}</a></td>
  <td>{{ a['adopter_name'] }}<br><span class="muted small">{{ a['adopter_email'] }}</span></td>
  <td><span class="small">{{ a['message'] or '—' }}</span></td>
  <td><span class="small">{{ a['created_at'][:16].replace('T',' ') }}</span></td>
  <td><form method="post" action="{{ url_for('admin_reject_app', app_id=a['id']) }}" class="form-row">
    <input type="text" name="reason" placeholder="Reason" style="flex:1 1 120px">
    <button class="btn btn-sm btn-danger">Reject</button></form></td>
</tr>{% endfor %}
</tbody></table>
{% else %}<p class="muted">No pending applications.</p>{% endif %}
<h3 class="mt-4">Active Reservations ({{ reservations|length }})</h3>
{% if reservations %}
  {% for d in reservations %}
    <div class="res-row">
      <span><a href="{{ url_for('dog_detail', dog_id=d['id']) }}">{{ d['name'] }}</a>
        — reserved until <strong>{{ d['reserved_until'][:10] }}</strong></span>
      <span class="form-row" style="margin:0">
        <form method="post" action="{{ url_for('admin_unreserve', dog_id=d['id']) }}" style="margin:0">
          <button class="btn btn-sm">Unreserve</button></form>
        <form method="post" action="{{ url_for('admin_adopt', dog_id=d['id']) }}" style="margin:0">
          <button class="btn btn-sm btn-success">Adopt</button></form>
      </span>
    </div>
  {% endfor %}
{% else %}<p class="muted">No active reservations.</p>{% endif %}
<h3 class="mt-4">All Dogs</h3>
<table><thead><tr><th>Name</th><th>Breed</th><th>Status</th><th>Reserved until</th><th>Actions</th></tr></thead><tbody>
{% for d in dogs %}<tr>
  <td><a href="{{ url_for('dog_detail', dog_id=d['id']) }}">{{ d['name'] }}</a></td>
  <td>{{ d['breed'] or '—' }}</td>
  <td><span class="badge badge-{{ d['status'] }}">{{ d['status'] }}</span></td>
  <td>{{ d['reserved_until'][:10] if d['reserved_until'] else '—' }}</td>
  <td><div class="form-row" style="margin:0;gap:4px">
    <a class="btn btn-sm" href="{{ url_for('admin_edit_dog', dog_id=d['id']) }}">Edit</a>
    {% if d['status'] == 'available' %}
      <form method="post" action="{{ url_for('admin_reserve', dog_id=d['id']) }}" style="margin:0">
        <button class="btn btn-sm btn-warning">Reserve 14d</button></form>
    {% elif d['status'] == 'reserved' %}
      <form method="post" action="{{ url_for('admin_unreserve', dog_id=d['id']) }}" style="margin:0">
        <button class="btn btn-sm">Unreserve</button></form>
      <form method="post" action="{{ url_for('admin_adopt', dog_id=d['id']) }}" style="margin:0">
        <button class="btn btn-sm btn-success">Adopt</button></form>
    {% endif %}
  </div></td>
</tr>{% endfor %}
</tbody></table>
{% endblock %}"""


DOG_FORM = """{% extends 'base' %}{% block content %}
<h1 class="mb-4">{{ 'Add Dog' if action == 'new' else 'Edit ' + dog['name'] }}</h1>
<form method="post" enctype="multipart/form-data" style="max-width:720px">
  <div class="row-2">
    <div class="field"><label>Name *</label>
      <input type="text" name="name" required value="{{ dog['name'] if dog else '' }}"></div>
    <div class="field"><label>Breed</label>
      <input type="text" name="breed" value="{{ dog['breed'] if dog else '' }}"></div>
  </div>
  <div class="row-2">
    <div class="field"><label>Age (years)</label>
      <input type="number" step="0.5" name="age_years"
             value="{{ dog['age_years'] if dog and dog['age_years'] is not none else '' }}"></div>
    <div class="field"><label>Sex</label>
      <select name="sex"><option value="">—</option>
        {% for s in ['male','female'] %}
          <option value="{{ s }}" {% if dog and dog['sex'] == s %}selected{% endif %}>{{ s }}</option>
        {% endfor %}
      </select></div>
  </div>
  <div class="field"><label>Photo {% if dog and dog['photo_filename'] %}(replace){% endif %}</label>
    <input type="file" name="photo" accept="image/*"></div>
  <div class="row-2">
    <div class="field"><label>Temperament</label>
      <input type="text" name="temperament" value="{{ dog['temperament'] if dog else '' }}"></div>
    <div class="field"><label>Health flags</label>
      <input type="text" name="health_flags" value="{{ dog['health_flags'] if dog else '' }}"></div>
  </div>
  <div class="field"><label>Description</label>
    <textarea name="description" rows="4">{{ dog['description'] if dog else '' }}</textarea></div>
  <button class="btn btn-primary">{{ 'Add dog' if action == 'new' else 'Save changes' }}</button>
  <a class="btn" href="{{ url_for('admin_dashboard') }}">Cancel</a>
</form>
{% endblock %}"""


TEMPLATES = {
    "base": BASE, "index": INDEX, "detail": DETAIL,
    "login": LOGIN, "register": REGISTER, "my_apps": MY_APPS,
    "admin": ADMIN, "dog_form": DOG_FORM,
}
app.jinja_loader = DictLoader(TEMPLATES)

# ---------------------------------------------------------------- public routes


@app.route("/")
def index():
    q = request.args.get("q", "").strip().lower()
    status_filter = request.args.get("status", "available")
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM dogs ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()
    dogs = [effective_dog(r) for r in rows]
    if status_filter == "available":
        dogs = [d for d in dogs if d["status"] == "available"]
    if q:
        dogs = [d for d in dogs
                if q in d["name"].lower() or q in (d["breed"] or "").lower()]
    return render_template("index", dogs=dogs)


@app.route("/dogs/<int:dog_id>")
def dog_detail(dog_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dogs WHERE id = ?", (dog_id,)).fetchone()
        if not row:
            abort(404)
        dog = effective_dog(row)
        activities = conn.execute(
            "SELECT * FROM activity WHERE dog_id = ? ORDER BY created_at DESC",
            (dog_id,),
        ).fetchall()
        my_app = None
        if current_user.is_authenticated and not current_user.is_admin:
            my_app = conn.execute(
                "SELECT * FROM applications WHERE dog_id = ? AND adopter_id = ?",
                (dog_id, int(current_user.id)),
            ).fetchone()
    finally:
        conn.close()
    return render_template("detail", dog=dog, activities=activities, my_app=my_app)


@app.route("/dogs/<int:dog_id>/apply", methods=["POST"])
@login_required
def apply(dog_id):
    if current_user.is_admin:
        abort(403)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dogs WHERE id = ?", (dog_id,)).fetchone()
        if not row:
            abort(404)
        if effective_dog(row)["status"] != "available":
            flash("This dog is no longer accepting applications.", "error")
            return redirect(url_for("dog_detail", dog_id=dog_id))
        try:
            conn.execute(
                "INSERT INTO applications (dog_id, adopter_id, message, created_at) "
                "VALUES (?, ?, ?, ?)",
                (dog_id, int(current_user.id),
                 request.form.get("message", "").strip(), now_iso()),
            )
            log_activity(conn, dog_id, "application",
                         "A new adoption application was submitted.")
            conn.commit()
        except sqlite3.IntegrityError:
            flash("You have already applied for this dog.", "error")
    finally:
        conn.close()
    flash("Application submitted!", "success")
    return redirect(url_for("dog_detail", dog_id=dog_id))


# ---------------------------------------------------------------- auth routes


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()
        if not (email and password and name):
            flash("All fields are required.", "error")
            return render_template("register")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register")
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users (email, password_hash, name, role, created_at) "
                "VALUES (?, ?, ?, 'adopter', ?)",
                (email, generate_password_hash(password), name, now_iso()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            flash("That email is already registered.", "error")
            return render_template("register")
        finally:
            conn.close()
        flash("Account created. Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
        finally:
            conn.close()
        if row and check_password_hash(row["password_hash"], password):
            login_user(User(row))
            return redirect(request.args.get("next") or url_for("index"))
        flash("Invalid email or password.", "error")
    return render_template("login")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/my-applications")
@login_required
def my_applications():
    if current_user.is_admin:
        return redirect(url_for("admin_dashboard"))
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT a.id, a.message, a.status, a.rejection_reason, a.created_at,
                      d.id AS dog_id, d.name AS dog_name, d.status AS dog_status,
                      d.reserved_until
               FROM applications a JOIN dogs d ON d.id = a.dog_id
               WHERE a.adopter_id = ? ORDER BY a.created_at DESC""",
            (int(current_user.id),),
        ).fetchall()
    finally:
        conn.close()
    apps = []
    for r in rows:
        r = dict(r)
        if r["dog_status"] == "reserved" and r["reserved_until"]:
            if parse_iso(r["reserved_until"]) < datetime.now(timezone.utc):
                r["dog_status"] = "available"
                r["reserved_until"] = None
        apps.append(r)
    return render_template("my_apps", apps=apps)


# ---------------------------------------------------------------- admin routes


@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    try:
        dog_rows = conn.execute(
            "SELECT * FROM dogs ORDER BY created_at DESC"
        ).fetchall()
        apps = conn.execute(
            """SELECT a.*, d.name AS dog_name, u.name AS adopter_name,
                      u.email AS adopter_email
               FROM applications a JOIN dogs d ON d.id = a.dog_id
               JOIN users u ON u.id = a.adopter_id
               WHERE a.status = 'pending' ORDER BY a.created_at DESC"""
        ).fetchall()
    finally:
        conn.close()
    dogs = [effective_dog(r) for r in dog_rows]
    reservations = [d for d in dogs if d["status"] == "reserved"]
    return render_template("admin", dogs=dogs, apps=apps, reservations=reservations)


@app.route("/admin/dogs/new", methods=["GET", "POST"])
@admin_required
def admin_new_dog():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "error")
            return render_template("dog_form", dog=None, action="new")
        filename = save_photo(request.files.get("photo"))
        conn = get_db()
        try:
            cur = conn.execute(
                """INSERT INTO dogs (name, breed, age_years, sex, temperament,
                   health_flags, description, photo_filename, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, request.form.get("breed", "").strip(),
                 parse_float(request.form.get("age_years")),
                 request.form.get("sex", "").strip(),
                 request.form.get("temperament", "").strip(),
                 request.form.get("health_flags", "").strip(),
                 request.form.get("description", "").strip(),
                 filename, now_iso()),
            )
            log_activity(conn, cur.lastrowid, "added", "Added to shelter.")
            conn.commit()
        finally:
            conn.close()
        flash("Dog added.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("dog_form", dog=None, action="new")


@app.route("/admin/dogs/<int:dog_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_dog(dog_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dogs WHERE id = ?", (dog_id,)).fetchone()
        if not row:
            abort(404)
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            if not name:
                flash("Name is required.", "error")
                return render_template("dog_form", dog=dict(row), action="edit")
            new_photo = save_photo(request.files.get("photo"))
            conn.execute(
                """UPDATE dogs SET name=?, breed=?, age_years=?, sex=?,
                   temperament=?, health_flags=?, description=?,
                   photo_filename=? WHERE id=?""",
                (name, request.form.get("breed", "").strip(),
                 parse_float(request.form.get("age_years")),
                 request.form.get("sex", "").strip(),
                 request.form.get("temperament", "").strip(),
                 request.form.get("health_flags", "").strip(),
                 request.form.get("description", "").strip(),
                 new_photo or row["photo_filename"], dog_id),
            )
            conn.commit()
            flash("Dog updated.", "success")
            return redirect(url_for("admin_dashboard"))
        dog = dict(row)
    finally:
        conn.close()
    return render_template("dog_form", dog=dog, action="edit")


@app.route("/admin/dogs/<int:dog_id>/reserve", methods=["POST"])
@admin_required
def admin_reserve(dog_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dogs WHERE id = ?", (dog_id,)).fetchone()
        if not row:
            abort(404)
        if effective_dog(row)["status"] != "available":
            flash("Only available dogs can be reserved.", "error")
            return redirect(request.referrer or url_for("admin_dashboard"))
        until = (datetime.now(timezone.utc)
                 + timedelta(days=RESERVATION_DAYS)).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE dogs SET status='reserved', reserved_until=? WHERE id=?",
            (until, dog_id),
        )
        log_activity(conn, dog_id, "reserved", f"Reserved until {until[:10]}.")
        conn.commit()
    finally:
        conn.close()
    flash(f"Dog reserved for {RESERVATION_DAYS} days.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin/dogs/<int:dog_id>/unreserve", methods=["POST"])
@admin_required
def admin_unreserve(dog_id):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE dogs SET status='available', reserved_until=NULL "
            "WHERE id=? AND status='reserved'",
            (dog_id,),
        )
        log_activity(conn, dog_id, "unreserved", "Reservation cancelled.")
        conn.commit()
    finally:
        conn.close()
    flash("Reservation cancelled.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin/dogs/<int:dog_id>/adopt", methods=["POST"])
@admin_required
def admin_adopt(dog_id):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE dogs SET status='adopted', reserved_until=NULL WHERE id=?",
            (dog_id,),
        )
        log_activity(conn, dog_id, "adopted", "Adopted!")
        conn.commit()
    finally:
        conn.close()
    flash("Dog marked as adopted.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/admin/applications/<int:app_id>/reject", methods=["POST"])
@admin_required
def admin_reject_app(app_id):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE applications SET status='rejected', rejection_reason=? "
            "WHERE id=?",
            (request.form.get("reason", "").strip(), app_id),
        )
        conn.commit()
    finally:
        conn.close()
    flash("Application rejected.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))


# ---------------------------------------------------------------- entry


if __name__ == "__main__":
    app.run(debug=True, port=8000)
