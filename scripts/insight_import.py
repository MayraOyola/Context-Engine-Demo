"""Write a Redis Insight import file for the demo's Redis database.

Reads the REDIS_* settings from .env and writes redis-insight-import.json, which can be loaded in
Redis Insight with "Add Redis database" -> "Import from file". The file contains the database
password, so it is gitignored; treat it like .env.

Usage: python scripts/insight_import.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "redis-insight-import.json"
CONNECTION_NAME = "Iris demo database"


def main() -> int:
    env = dotenv_values(ROOT / ".env")
    host = (env.get("REDIS_HOST") or "").strip()
    if not host:
        print("No REDIS_HOST in .env yet; skipping the Redis Insight import file.")
        return 0
    entry = {
        "name": CONNECTION_NAME,
        "host": host,
        "port": int(env.get("REDIS_PORT") or 6379),
        "username": env.get("REDIS_USERNAME") or "default",
        "db": int(env.get("REDIS_DB") or 0),
        "tls": (env.get("REDIS_SSL") or "false").strip().lower() in ("1", "true", "yes"),
        "connectionType": "STANDALONE",
    }
    if env.get("REDIS_PASSWORD"):
        entry["password"] = env["REDIS_PASSWORD"]
    OUTPUT.write_text(json.dumps([entry], indent=2) + "\n")
    os.chmod(OUTPUT, 0o600)
    print(f"Redis Insight import file: {OUTPUT.name} (download it, then Add Redis database > Import from file)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
