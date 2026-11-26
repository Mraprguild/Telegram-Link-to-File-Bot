import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, RPCError

from config import (
    API_ID, API_HASH, BOT_TOKEN, USER_SESSION, STORAGE_CHAT_ID,
    ADMIN_IDS, MAX_FILE_SIZE_GB, PART_SIZE_MB, MAX_CONCURRENT_JOBS,
    DASHBOARD_HOST, DASHBOARD_PORT, DASHBOARD_TOKEN, DOWNLOAD_TIMEOUT,
)
from database import Database
from downloader import stream_link_to_channel
from dashboard import start_dashboard
from state import STATE

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("link-file-bot")

bot = Client("link_file_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user = Client("link_file_user", api_id=API_ID, api_hash=API_HASH, session_string=USER_SESSION)
db = Database(os.getenv("DATABASE_PATH", "data/bot.sqlite3"))
semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
jobs = {}
started_at = time.time()


def human_bytes(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def is_admin(user_id):
    return user_id in ADMIN_IDS


async def safe_edit(message, text):
    try:
        await message.edit_text(text, disable_web_page_preview=True)
    except Exception:
        pass


@bot.on_message(filters.private & filters.command("start"))
async def start_handler(_, message):
    await message.reply_text(
        "👋 **Link-to-File Bot**\n\n"
        "Send a direct HTTP/HTTPS download link and I will download it "
        "and deliver it as Telegram document(s).\n\n"
        "• Large files are split into safe-sized parts\n"
        "• Live download/upload progress and ETA\n"
        "• `/status` — bot and server status\n"
        "• `/myfiles` — your recent conversions\n"
        "• `/cancel` — cancel your active conversion\n"
        "• `/help` — usage and limitations",
        disable_web_page_preview=True,
    )


@bot.on_message(filters.private & filters.command("help"))
async def help_handler(_, message):
    await message.reply_text(
        "**How to use**\n"
        "1. Copy a direct `http://` or `https://` file URL.\n"
        "2. Paste it here.\n"
        "3. Wait while the bot downloads and uploads the file.\n"
        "4. If it is larger than one Telegram part, you will receive numbered parts.\n\n"
        "**Important:** This bot accepts direct downloadable URLs, not ordinary "
        "web pages, login-protected links, or links requiring browser cookies. "
        "The remote server must permit access. Telegram size limits still apply.",
        disable_web_page_preview=True,
    )


@bot.on_message(filters.private & filters.command("status"))
async def status_handler(_, message):
    uptime = int(time.time() - started_at)
    d, rem = divmod(uptime, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    active = STATE.snapshot().get("active_jobs", 0)
    await message.reply_text(
        "🟢 **Bot status: Running**\n"
        f"⏱ Uptime: `{d}d {h}h {m}m {s}s`\n"
        f"⚙️ Active transfers: `{active}`\n"
        f"📦 Maximum configured file size: `{MAX_FILE_SIZE_GB} GB`\n"
        f"🧩 Part size: `{PART_SIZE_MB} MB`\n"
        f"🕒 Server time: `{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}`"
    )


@bot.on_message(filters.private & filters.command("stats"))
async def stats_handler(_, message):
    snap = STATE.snapshot()
    if not is_admin(message.from_user.id):
        await message.reply_text(
            f"📊 Completed conversions: `{snap['completed_jobs']}`\n"
            f"⚙️ Active transfers: `{snap['active_jobs']}`"
        )
        return
    await message.reply_text(
        "📊 **Admin statistics**\n"
        f"Completed: `{snap['completed_jobs']}`\n"
        f"Failed: `{snap['failed_jobs']}`\n"
        f"Active: `{snap['active_jobs']}`\n"
        f"Total transferred: `{human_bytes(snap['total_bytes'])}`"
    )


@bot.on_message(filters.private & filters.command("myfiles"))
async def myfiles_handler(_, message):
    rows = db.recent_for_user(message.from_user.id, limit=10)
    if not rows:
        await message.reply_text("You have no completed conversions yet.")
        return
    lines = ["**Your recent conversions**"]
    for row in rows:
        lines.append(
            f"• `{row['created_at']}` — {row['filename']} "
            f"({human_bytes(row['size_bytes'])}, {row['parts']} part(s))"
        )
    await message.reply_text("\n".join(lines))


@bot.on_message(filters.private & filters.command("cancel"))
async def cancel_handler(_, message):
    event = jobs.get(message.from_user.id)
    if not event:
        await message.reply_text("You do not have an active transfer.")
        return
    event.set()
    await message.reply_text("🛑 Cancellation requested. The current part will stop shortly.")


@bot.on_message(filters.private & filters.text & ~filters.command(
    ["start", "help", "status", "stats", "myfiles", "cancel"]
))
async def link_handler(_, message):
    user_id = message.from_user.id
    url = (message.text or "").strip()
    if not (url.startswith("https://") or url.startswith("http://")):
        await message.reply_text("Please send a direct `http://` or `https://` download link.")
        return
    if user_id in jobs:
        await message.reply_text("You already have an active transfer. Use `/cancel` first.")
        return

    cancel_event = asyncio.Event()
    jobs[user_id] = cancel_event
    status_msg = await message.reply_text("🔎 Checking link and preparing transfer…")
    STATE.job_started(user_id, url)

    async def progress(text):
        await safe_edit(status_msg, text)

    try:
        async with semaphore:
            await stream_link_to_channel(
                url=url,
                requester_id=user_id,
                bot_client=bot,
                user_client=user,
                storage_chat_id=STORAGE_CHAT_ID,
                cancel_event=cancel_event,
                progress=progress,
                db=db,
                max_size_bytes=MAX_FILE_SIZE_GB * 1024**3,
                part_size_bytes=PART_SIZE_MB * 1024**2,
                timeout=DOWNLOAD_TIMEOUT,
            )
        STATE.job_completed(user_id)
        await safe_edit(status_msg, "✅ **Transfer completed.** Check the documents sent above.")
    except asyncio.CancelledError:
        STATE.job_failed(user_id)
        await safe_edit(status_msg, "🛑 Transfer cancelled.")
    except Exception as exc:
        STATE.job_failed(user_id)
        log.exception("Transfer failed for user %s", user_id)
        short = str(exc).replace("`", "'")[:700]
        await safe_edit(status_msg, f"❌ **Transfer failed**\n`{short}`\n\nSend another direct download link to retry.")
    finally:
        jobs.pop(user_id, None)


async def main():
    os.makedirs("data", exist_ok=True)
    await db.initialize()
    await bot.start()
    try:
        await user.start()
        STATE.set_bot_status(True)
        start_dashboard(DASHBOARD_HOST, DASHBOARD_PORT, DASHBOARD_TOKEN, started_at)
        log.info("Bot and MTProto user session started")
        await asyncio.Event().wait()
    finally:
        STATE.set_bot_status(False)
        await user.stop()
        await bot.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Shutdown requested")
