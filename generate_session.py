"""Generate USER_SESSION for the MTProto user account."""
import asyncio
import os
from pyrogram import Client

async def main():
    api_id = int(os.getenv("API_ID") or input("API_ID: ").strip())
    api_hash = os.getenv("API_HASH") or input("API_HASH: ").strip()
    async with Client("session_generator", api_id=api_id, api_hash=api_hash, in_memory=True) as app:
        print("\nUSER_SESSION=\n" + await app.export_session_string())
        print("\nKeep this string secret. Do not commit it to GitHub.")

if __name__ == "__main__":
    asyncio.run(main())
