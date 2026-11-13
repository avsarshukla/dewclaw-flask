```markdown
1. Go to the project folder:

   ```bash
   cd ~/dewclaw-flask

```

2. Confirm `app.py` has the right port:
```bash
grep "port=" app.py

```


You should see exactly one line, ending in `port=8000)`.
3. Start Flask:
```bash
venv/Scripts/python.exe app.py

```


Watch the output carefully. You want to see, in this order, with no traceback:
```text
- Serving Flask app 'app'
- Debug mode: on
WARNING: This is a development server...
- Running on [http://127.0.0.1:8000](http://127.0.0.1:8000)
Press CTRL+C to quit

```


Now stop. Do not touch this window. Don't press `Ctrl+C`. Don't type anything. The cursor must sit at the end of `Debugger PIN: ...` with no `$` prompt returning. If the `$` prompt comes back, Flask exited — paste the error text that appears above it.
4. Open a second Git Bash window (the Git Bash icon in the Start menu, not a new tab in the same window — though either works as long as it's not the Flask window).
In that second window:
```bash
netstat -ano | findstr :8000

```


Now you should get output like:
```text
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       12345

```


If you get that, the server is live. Then:
```bash
curl [http://127.0.0.1:8000](http://127.0.0.1:8000)

```


Open the browser to `http://127.0.0.1:8000`

```

```
