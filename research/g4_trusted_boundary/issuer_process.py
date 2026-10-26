"""Provisioner-owned test launcher; request handle never contains a signing key."""

import json
from pathlib import Path
import subprocess
import sys
from research.g4_trusted_boundary.runtime import Proof, Refused


class ProcessIssuer:
    def __init__(self, key, approved_hash):
        self.process = subprocess.Popen(
            [sys.executable, "-B", str(Path(__file__).with_name("issuer_worker.py"))],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf8",
        )
        self.process.stdin.write(
            json.dumps(dict(key=key.hex(), validator_hash=approved_hash)) + "\n"
        )
        self.process.stdin.flush()
        if self.process.stdout.readline().strip() != "READY":
            self.close()
            raise Refused("trusted_validator_unavailable")

    def issue(self, seal):
        try:
            self.process.stdin.write(json.dumps(dict(seal=seal)) + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
            if not line:
                raise Refused("trusted_validator_unavailable")
            value = json.loads(line)
            if "error" in value:
                raise Refused(value["error"])
            return Proof(**{**value, "mac": bytes.fromhex(value["mac"])})
        except (OSError, ValueError):
            raise Refused("trusted_validator_unavailable") from None

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)
        try:
            self.process.stdin.close()
        except OSError as exc:
            # A failed request can leave buffered bytes after the signer died.
            # Windows reports EINVAL on close's final flush (Unix EPIPE).
            # The child is already reaped; retain every other cleanup failure.
            if exc.errno not in (22, 32):
                raise
        self.process.stdout.close()
