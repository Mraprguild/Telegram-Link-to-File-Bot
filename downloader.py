import asyncio
import ipaddress
import os
import re
import socket
import tempfile
import time
from urllib.parse import urlparse, unquote

import aiohttp

from state import STATE

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
CHUNK = 1024 * 1024


def safe_filename(value):
    value = unquote(value or "download.bin")
    value = value.replace("\\", "/").split("/")[-1]
    value = re.sub(r"[^A-Za-z0-9._() -]", "_", value).strip(" .")
    return (value[:180] or "download.bin")


async def validate_public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only valid HTTP/HTTPS URLs are supported.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not allowed.")
    host = parsed.hostname.rstrip(".")
    if host.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Localhost URLs are blocked.")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise ValueError("Could not resolve the download host.") from exc
    addresses = {item[4][0] for item in infos}
    if not addresses:
        raise ValueError("The download host did not resolve.")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global:
            raise ValueError("Private, local, and reserved network addresses are blocked.")
    return url


async def open_checked(session, url):
    current = url
    for _ in range(6):
        await validate_public_url(current)
        response = await session.get(current, allow_redirects=False)
        if response.status in REDIRECT_STATUSES:
            location = response.headers.get("Location")
            response.release()
            if not location:
                raise RuntimeError(f"Redirect {response.status} did not include a destination.")
            from urllib.parse import urljoin
            current = urljoin(current, location)
            continue
        response.raise_for_status()
        return response, current
    raise RuntimeError("Too many redirects.")


def filename_from_headers(headers, final_url):
    disposition = headers.get("Content-Disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8''|\"?)([^\";]+)", disposition, re.I)
    if match:
        return safe_filename(match.group(1).strip('"'))
    return safe_filename(os.path.basename(urlparse(final_url).path) or "download.bin")


def human_bytes(value):
    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}/s"
        value /= 1024
    return f"{value:.1f} TB/s"


def human_time(seconds):
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "calculating"
    seconds = int(seconds)
    return f"{seconds//3600}h {(seconds%3600)//60}m {seconds%60}s"


async def stream_link_to_channel(
    url, requester_id, bot_client, user_client, storage_chat_id,
    cancel_event, progress, db, max_size_bytes, part_size_bytes, timeout
):
    if part_size_bytes < 10 * 1024 * 1024 or part_size_bytes > 1950 * 1024 * 1024:
        raise ValueError("PART_SIZE_MB must be between 10 and 1950.")
    client_timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=timeout)
    connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=0)
    headers = {"User-Agent": "Telegram-Link-File-Bot/1.0"}
    total = 0
    part_number = 0
    started = time.monotonic()
    last_update = 0
    uploaded_message_ids = []
    source_host = urlparse(url).hostname or ""

    async with aiohttp.ClientSession(timeout=client_timeout, connector=connector, headers=headers) as session:
        response, final_url = await open_checked(session, url)
        async with response:
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type:
                raise ValueError("This URL returned a web page, not a direct file. Use a direct download URL.")
            declared = response.headers.get("Content-Length")
            expected = int(declared) if declared and declared.isdigit() else None
            if expected and expected > max_size_bytes:
                raise ValueError(f"File exceeds configured maximum of {max_size_bytes // (1024**3)} GB.")
            filename = filename_from_headers(response.headers, final_url)
            await progress(f"⬇️ **Downloading:** `{filename}`\nSize: `{expected or 'unknown'}` bytes\nPreparing first part…")

            part_file = None
            part_path = None
            part_bytes = 0
            downloaded = 0

            async def begin_part():
                nonlocal part_file, part_path, part_bytes, part_number
                part_number += 1
                fd, part_path = tempfile.mkstemp(prefix="tg-part-", suffix=".bin")
                part_file = os.fdopen(fd, "wb")
                part_bytes = 0

            async def upload_part():
                nonlocal part_file, part_path, part_bytes
                if not part_file:
                    return
                part_file.close()
                part_name = filename if part_number == 1 and (expected is None or expected <= part_size_bytes) else f"{filename}.part{part_number:03d}"
                if expected and expected > part_size_bytes and part_number == 1:
                    part_name = f"{filename}.part{part_number:03d}"
                caption = f"📦 {filename}\nPart {part_number}" + (f" of {((expected + part_size_bytes - 1)//part_size_bytes)}" if expected else "")
                upload_started = time.monotonic()
                last_upload = {"time": upload_started, "bytes": 0}

                def upload_progress(current, total_upload):
                    now = time.monotonic()
                    if now - last_upload["time"] >= 2 or current == total_upload:
                        delta = current - last_upload["bytes"]
                        speed = delta / max(now - last_upload["time"], 0.001)
                        last_upload.update(time=now, bytes=current)
                        percent = (current / total_upload * 100) if total_upload else 0
                        STATE.update_job(requester_id, phase=f"Uploading part {part_number}", percent=round(percent, 1), speed=human_bytes(speed))
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(progress(
                                f"⬆️ **Uploading part {part_number}:** `{part_name}`\n"
                                f"Progress: `{percent:.1f}%`\nSpeed: `{human_bytes(speed)}`"
                            ))
                        except RuntimeError:
                            pass

                try:
                    stored = await user_client.send_document(
                        chat_id=storage_chat_id,
                        document=part_path,
                        file_name=part_name,
                        caption=caption[:1024],
                        progress=upload_progress,
                    )
                    uploaded_message_ids.append(stored.id)
                    STATE.add_bytes(part_bytes)
                    await progress(f"📤 Uploaded part `{part_number}`. Preparing delivery…")
                    copied = await bot_client.copy_message(
                        chat_id=requester_id,
                        from_chat_id=storage_chat_id,
                        message_id=stored.id,
                    )
                    return copied
                finally:
                    try:
                        os.remove(part_path)
                    except OSError:
                        pass
                    part_file = None
                    part_path = None
                    part_bytes = 0

            async for block in response.content.iter_chunked(CHUNK):
                if cancel_event.is_set():
                    raise asyncio.CancelledError()
                if not block:
                    continue
                offset = 0
                while offset < len(block):
                    if total >= max_size_bytes:
                        raise ValueError(f"File exceeded configured maximum of {max_size_bytes // (1024**3)} GB.")
                    if part_file is None:
                        await begin_part()
                    capacity = part_size_bytes - part_bytes
                    piece = block[offset:offset + capacity]
                    part_file.write(piece)
                    piece_len = len(piece)
                    part_bytes += piece_len
                    total += piece_len
                    downloaded += piece_len
                    offset += piece_len
                    if part_bytes >= part_size_bytes:
                        await upload_part()
                    now = time.monotonic()
                    if now - last_update >= 2:
                        elapsed = max(now - started, 0.001)
                        speed = downloaded / elapsed
                        percent = (downloaded / expected * 100) if expected else 0
                        eta = (expected - downloaded) / speed if expected and speed > 0 else None
                        STATE.update_job(requester_id, phase="Downloading", percent=round(percent, 1),
                                         speed=human_bytes(speed), eta=human_time(eta))
                        await progress(
                            f"⬇️ **Downloading:** `{filename}`\n"
                            f"Downloaded: `{downloaded / 1024**2:.1f} MB`"
                            + (f" / `{expected / 1024**2:.1f} MB`" if expected else "")
                            + f"\nProgress: `{percent:.1f}%`"
                            + f"\nSpeed: `{human_bytes(speed)}`"
                            + f"\nElapsed: `{human_time(elapsed)}` | ETA: `{human_time(eta)}`"
                            + f"\nParts delivered: `{len(uploaded_message_ids)}`"
                        )
                        last_update = now

            if part_file is not None and part_bytes:
                await upload_part()
            elif total == 0:
                raise ValueError("The URL returned an empty file.")

            if expected and total < expected:
                raise RuntimeError(f"Download ended early: received {total} of {expected} bytes.")
            db.add(requester_id, filename, total, len(uploaded_message_ids), source_host)
            await progress(
                f"✅ **Finished:** `{filename}`\n"
                f"Total size: `{total / 1024**3:.2f} GB`\n"
                f"Telegram documents delivered: `{len(uploaded_message_ids)}`"
            )
