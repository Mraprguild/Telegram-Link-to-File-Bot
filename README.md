# Telegram Link-to-File Bot

A Python Telegram bot that accepts a **direct HTTP/HTTPS download URL**, streams the remote file to temporary disk in bounded parts, uploads each part through a Telegram MTProto user session to a private storage channel, and delivers the stored messages to the requester through the bot.

Includes live transfer progress, ETA, speed, cancellation, SQLite history, health endpoint, and a responsive server dashboard.

## Features

- Direct HTTP/HTTPS file links (not arbitrary web pages or browser-only links).
- Streaming download; does not load a whole multi-GB file into RAM.
- Splits large files into Telegram-safe documents (default 1,900 MB each).
- MTProto upload via a separately authenticated Telegram user session.
- Storage channel staging; bot copies each uploaded document to the requesting user.
- Download/upload progress, speed, elapsed time, and ETA.
- `/start`, `/help`, `/status`, `/stats`, `/myfiles`, `/cancel`.
- Dashboard with bot status, process/system uptime, active jobs, CPU, RAM, disk and transfer totals.
- SSRF protections: blocks localhost/private/reserved IP destinations and validates redirect targets.
- SQLite conversion history, Docker and Render worker configuration.

## Important Telegram limits and architecture

This project **does not create a single 5 GB Telegram document**. It splits large files into multiple documents. The default 1,900 MB part size is intentionally conservative for compatibility. A 5 GB file will normally become three documents.

The MTProto user account uploads each part to a private storage channel. The bot must also be an administrator in that channel so it can copy the messages to the requester. The user account needs permission to post there.

Telegram, account type, client library, and Bot API limits can change. This project cannot promise unlimited file size or instant transfer. Actual speed depends on the source host, network, Telegram rate limits, server bandwidth, and available disk throughput.

## Requirements

- Python 3.11+
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org)
- A Telegram user account session string (MTProto)
- A private Telegram channel where both the user account and bot are admins
- Enough temporary disk space for at least one part (default up to 1,900 MB)
- A VPS or persistent Docker host recommended for nonstop operation

## 1. Create the storage channel

1. Create a private Telegram channel.
2. Add the MTProto user account that will generate `USER_SESSION`.
3. Promote that user account so it can post messages.
4. Add your bot and promote it with permission to post messages.
5. Obtain the channel ID (usually a value beginning with `-100`).
6. Set it as `STORAGE_CHAT_ID`.

Keep the channel private. Files are staged there before the bot copies them to users.

## 2. Install and configure

```bash
git clone https://github.com/YOUR_USERNAME/Telegram-Link-File-Bot.git
cd Telegram-Link-File-Bot
python -m venv .venv
source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your credentials.

Generate the MTProto session string:

```bash
python generate_session.py
```

Sign in with the Telegram user account intended for uploads. Copy the printed string into `USER_SESSION` in `.env`. Treat it like a password. Never publish it or commit it to GitHub.

Run:

```bash
python bot.py
```

Dashboard: `http://YOUR_SERVER_IP:8080/?token=YOUR_DASHBOARD_TOKEN`

Health check: `http://YOUR_SERVER_IP:8080/health`

If `DASHBOARD_TOKEN` is empty, the dashboard is public. Set a long random secret before exposing it to the internet. Prefer putting the dashboard behind HTTPS and a reverse proxy/firewall.

## 3. Docker deployment

```bash
cp .env.example .env
# Edit .env
docker compose up -d --build
docker compose logs -f
```

The Compose file mounts `./data` so the SQLite database survives container replacement. The bot process is restarted automatically by Docker's `restart: unless-stopped` policy.

## 4. Render deployment

This repository includes `render.yaml` as a Docker **Background Worker**. Create the service from the repository and enter all required environment variables in Render.

A background worker is suitable for nonstop bot polling. Render's ephemeral filesystem is not durable; use a persistent disk or external database if you need history to survive redeployments. The dashboard port is exposed by the container, but a Render Background Worker does not provide a public web URL. Deploy `dashboard.py` as a separate web service or use a VPS if you need a public dashboard.

## Commands

| Command | Description |
|---|---|
| `/start` | Start and usage overview |
| `/help` | Instructions and limitations |
| `/status` | Bot state, uptime and active transfers |
| `/stats` | Transfer counters (admins see full totals) |
| `/myfiles` | Your last 10 completed conversions |
| `/cancel` | Cancel your active transfer |

Send a direct file URL as a normal message to start a conversion.

## Configuration

| Variable | Default | Description |
|---|---:|---|
| `MAX_FILE_SIZE_GB` | `20` | Maximum total remote download size |
| `PART_SIZE_MB` | `1900` | Size of each Telegram document part (10–1950 MB) |
| `MAX_CONCURRENT_JOBS` | `1` | Concurrent transfers; start conservatively |
| `DOWNLOAD_TIMEOUT` | `90` | Socket read timeout in seconds |
| `DASHBOARD_TOKEN` | empty | Dashboard access token; set this in production |
| `STORAGE_CHAT_ID` | required | Private channel ID used for staging |
| `ADMIN_IDS` | empty | Comma-separated Telegram numeric user IDs |

## Security and operational notes

- Only use URLs for files you are authorized to download and redistribute.
- The downloader blocks non-public IP ranges and re-checks redirects to reduce SSRF risk. Keep the host OS and dependencies patched.
- Do not expose `.env`, session strings, SQLite files, or the private storage channel.
- The dashboard shows server metrics and transfer URLs; protect it with a strong token and HTTPS.
- Use a VPS with reliable outbound network and sufficient disk space for stable 24/7 service.
- Do not run multiple bot instances with the same bot token/session simultaneously.
- A transfer can fail if the source requires cookies, authentication, anti-bot JavaScript, or does not support direct downloads.
- Telegram FloodWait/rate limits and source throttling can delay a transfer. “Instant” speed cannot be guaranteed.
- If a transfer is interrupted during an upload, the current part may need to be downloaded/uploaded again. Full cross-restart resume is not implemented.
- The bot uses temporary local disk for one part at a time. Make sure the server has adequate free disk space.
- Configure backups for `data/bot.sqlite3` if conversion history matters.

## Troubleshooting

**Bot starts but does not respond**
- Check `BOT_TOKEN`, logs, and that only one process is polling with this token.
- Confirm the user has pressed `/start` on the bot.

**MTProto user login fails**
- Regenerate `USER_SESSION` with the correct API ID/hash and verify the account is active.
- Keep the session string private; revoke the session in Telegram if exposed.

**Upload to storage channel fails**
- Confirm the user account is a channel admin with post permission.
- Confirm `STORAGE_CHAT_ID` is correct.
- Confirm the bot is an admin with permission to post/copy messages.

**Bot cannot copy the uploaded message**
- Check bot membership/admin rights in the private storage channel.
- Check that the uploaded media type and size are supported by the bot/client API.

**Dashboard returns 401**
- Open the dashboard with `?token=YOUR_DASHBOARD_TOKEN`.
- Do not share the token URL.

**Link rejected**
- Use a direct file URL, not a page with a download button.
- Private/local IPs are blocked intentionally.
- The remote host must allow automated HTTP downloads.

## Project layout

```text
.
├── bot.py
├── config.py
├── downloader.py
├── dashboard.py
├── state.py
├── database.py
├── generate_session.py
├── templates/dashboard.html
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── render.yaml
└── .env.example
```

## License

MIT. Add a `LICENSE` file with your chosen copyright holder before publishing if you want to distribute this project under the MIT License.
