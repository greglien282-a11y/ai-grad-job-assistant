"""Disposable DB worker killed by tests. No model process or runtime factory."""

import json
from pathlib import Path
import sys
from uuid import UUID
import psycopg
from psycopg.rows import dict_row

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root), str(root / "apps/api")]
from research.g3_choice_protocol.runtime import apply


def main():
    # Synthetic test connection/credential delivered through stdin, never argv.
    config = json.loads(sys.stdin.readline())
    with psycopg.connect(config["dsn"], row_factory=dict_row) as db:
        apply(db, UUID(config["sid"]), config["token"], config["key"], config["body"])
        if config["point"] == "before_commit":
            print("STAGED", flush=True)
            sys.stdin.readline()  # parent kills this real process before COMMIT
        else:
            db.commit()
            print("COMMITTED", flush=True)
            sys.stdin.readline()  # response is deliberately never delivered


if __name__ == "__main__":
    main()
