import os

def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

API_ID = int(required("API_ID"))
API_HASH = required("API_HASH")
BOT_TOKEN = required("BOT_TOKEN")
USER_SESSION = required("USER_SESSION")
STORAGE_CHAT_ID = int(required("STORAGE_CHAT_ID"))

ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
}
MAX_FILE_SIZE_GB = int(os.getenv("MAX_FILE_SIZE_GB", "20"))
# Keep each document below 2 GB for broad account compatibility.
PART_SIZE_MB = int(os.getenv("PART_SIZE_MB", "1900"))
MAX_CONCURRENT_JOBS = max(1, int(os.getenv("MAX_CONCURRENT_JOBS", "1")))
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "90"))
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "8080")))
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")
