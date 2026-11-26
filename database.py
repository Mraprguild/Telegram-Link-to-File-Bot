import sqlite3
import os
from datetime import datetime, timezone

class Database:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    async def initialize(self):
        with sqlite3.connect(self.path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS conversions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    parts INTEGER NOT NULL,
                    source_host TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_conversions_user ON conversions(user_id, id DESC)")

    def add(self, user_id, filename, size_bytes, parts, source_host):
        with sqlite3.connect(self.path) as con:
            con.execute(
                "INSERT INTO conversions(user_id,filename,size_bytes,parts,source_host,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, filename, size_bytes, parts, source_host,
                 datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
            )

    def recent_for_user(self, user_id, limit=10):
        with sqlite3.connect(self.path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT filename,size_bytes,parts,created_at FROM conversions WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
            return [dict(row) for row in rows]
