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
