"""Real process killed by test parent; input contains only synthetic secrets."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/api"))
import psycopg
from psycopg.rows import dict_row
from research.g4_trusted_boundary.runtime import Issuer, submit


def main():
    data = json.loads(sys.stdin.readline())
    gate = SimpleNamespace(**data["gate"])
    b = SimpleNamespace(**data["b"])
    b.sid = UUID(b.sid)
    issuer = Issuer(bytes.fromhex(data["secret"]), gate.validator_hash)
    with psycopg.connect(data["dsn"], row_factory=dict_row) as db:
        submit(db, gate, b, "crash", data["body"], issuer=issuer)
        print("STAGED", flush=True)
        if sys.stdin.readline().strip() != "COMMIT":
            return
        db.commit()
        print("COMMITTED", flush=True)
        sys.stdin.readline()


if __name__ == "__main__":
    main()
