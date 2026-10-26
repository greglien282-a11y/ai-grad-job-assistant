"""Private pipe service, separate PID, synthetic key passed once via stdin.

No HTTP listener/environment discovery. OS/process/key custody remains a trust
assumption; this is not a hardware security module or production service.
"""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/api"))
from research.g4_trusted_boundary.runtime import Issuer, Refused


def main():
    setup = json.loads(sys.stdin.readline())
    issuer = Issuer(bytes.fromhex(setup["key"]), setup["validator_hash"])
    print("READY", flush=True)
    for line in sys.stdin:
        try:
            proof = issuer.issue(json.loads(line)["seal"])
            result = dict(
                seal=proof.seal,
                nonce=proof.nonce,
                expires=proof.expires,
                validator_hash=proof.validator_hash,
                mac=proof.mac.hex(),
            )
        except Refused as exc:
            result = dict(error=str(exc))
        except Exception:
            result = dict(error="trusted_validator_unavailable")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
