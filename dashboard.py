import threading
import time
import psutil
from flask import Flask, jsonify, render_template, request, abort
from state import STATE

app = Flask(__name__)
_dashboard_token = ""
_started_at = time.time()

def authorized():
    if not _dashboard_token:
        return True
    supplied = request.headers.get("X-Dashboard-Token") or request.args.get("token", "")
    return supplied == _dashboard_token

@app.before_request
def protect_dashboard():
    if not authorized():
        abort(401)

@app.get("/")
def home():
    return render_template("dashboard.html")

@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "telegram-link-file-bot"})

@app.get("/api/status")
def api_status():
    snap = STATE.snapshot()
    boot = psutil.boot_time()
    snap.update({
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": psutil.virtual_memory().percent,
        "ram_used": psutil.virtual_memory().used,
        "ram_total": psutil.virtual_memory().total,
        "disk_percent": psutil.disk_usage(".").percent,
        "server_uptime": int(time.time() - _started_at),
        "system_uptime": int(time.time() - boot),
    })
    return jsonify(snap)

def start_dashboard(host, port, token, started_at):
    global _dashboard_token, _started_at
    _dashboard_token = token
    _started_at = started_at
    thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True),
        daemon=True,
        name="dashboard",
    )
    thread.start()
    return thread
