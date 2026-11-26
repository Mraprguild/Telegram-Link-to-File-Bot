import threading
import time

class RuntimeState:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {
            "bot_running": False, "active_jobs": 0, "completed_jobs": 0,
            "failed_jobs": 0, "total_bytes": 0, "current": {},
            "started_at": time.time(),
        }

    def snapshot(self):
        with self.lock:
            result = dict(self.data)
            result["current"] = dict(self.data["current"])
            result["uptime_seconds"] = int(time.time() - self.data["started_at"])
            return result

    def set_bot_status(self, running):
        with self.lock:
            self.data["bot_running"] = running

    def job_started(self, user_id, url):
        with self.lock:
            self.data["active_jobs"] += 1
            self.data["current"][str(user_id)] = {
                "url": url[:160], "phase": "Preparing", "percent": 0,
                "speed": "—", "eta": "—", "updated": time.time()
            }

    def update_job(self, user_id, **values):
        with self.lock:
            job = self.data["current"].get(str(user_id))
            if job:
                job.update(values)
                job["updated"] = time.time()

    def job_completed(self, user_id):
        with self.lock:
            self.data["active_jobs"] = max(0, self.data["active_jobs"] - 1)
            self.data["completed_jobs"] += 1
            self.data["current"].pop(str(user_id), None)

    def job_failed(self, user_id):
        with self.lock:
            self.data["active_jobs"] = max(0, self.data["active_jobs"] - 1)
            self.data["failed_jobs"] += 1
            self.data["current"].pop(str(user_id), None)

    def add_bytes(self, amount):
        with self.lock:
            self.data["total_bytes"] += int(amount)

STATE = RuntimeState()
