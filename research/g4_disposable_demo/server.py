"""Loopback disposable research demo. NOT Pathwise HTTP or formal CO3.

Provisions test fixtures before listening; owner NEVER handles HTTP. The only
writer is a restricted LOGIN with independent signer and G4 DB permit gate.
No production URL discovery, factory, accounts, Provider or migration.
"""

import argparse
from contextlib import contextmanager
import hashlib
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
from threading import Lock, Thread
from types import SimpleNamespace
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))
from psycopg import Error as DatabaseError
from research.g3_choice_protocol.runtime import command, Refused
from research.g3_choice_protocol.projection import project
from research.g4_trusted_boundary.runtime import submit, read
from research.g4_trusted_boundary.issuer_process import ProcessIssuer

SAMPLES = (
    "我部署了服务。",
    "我编写了脚本。",
    "我测试了导出按钮。",
    "我整理了27条缺失记录。",
    "我制作了👩‍💻原型图。",
    "我计划部署服务。",
    "我正在部署服务。",
    "我们部署了服务。",
    "我没有部署服务。",
)


class NotSaved(Refused):
    pass


@contextmanager
def provision():
    """Reuse test-only fixture lifecycle, not a new runtime factory.

    No environment toggle grants production admission: only an explicit test
    URL accepted by the unchanged loopback/database-name fixture can provision.
    """
    from research.g3_choice_protocol.conftest import model
    from research.g4_trusted_boundary.conftest import boundary

    old = os.environ.get("G3_TEST_DATABASE_URL")
    value = os.environ.get("G4_DEMO_TEST_DATABASE_URL")
    if not value:
        raise ValueError("explicit_synthetic_database_required")
    os.environ["G3_TEST_DATABASE_URL"] = value
    outer = model.__wrapped__()
    inner = None
    try:
        m = next(outer)
        inner = boundary.__wrapped__(m, SimpleNamespace(param="credential"))
        yield next(inner)
    finally:
        if inner:
            inner.close()
        outer.close()
        if old is None:
            os.environ.pop("G3_TEST_DATABASE_URL", None)
        else:
            os.environ["G3_TEST_DATABASE_URL"] = old


class Demo:
    def __init__(self, x):
        self.x = x
        self.b = x.model.seed()  # provisioning, BEFORE HTTP starts
        self.signer = ProcessIssuer(x.secret, x.gate.validator_hash)
        self.lock = Lock()
        self.command_lock = Lock()
        self.cookie = secrets.token_urlsafe(32)

    def issue(self, seal):
        with self.lock:
            return self.signer.issue(seal)

    def save(self, key, payload):
        with self.command_lock:
            return self._save(key, payload)

    def _save(self, key, payload):
        if (
            type(payload) is not dict
            or set(payload)
            != {
                "demo_contract",
                "synthetic",
                "content",
                "kind",
                "stage",
                "lose_response",
            }
            or payload["demo_contract"] != "g4-disposable-submit-v1"
            or payload["synthetic"] is not True
            or type(payload["lose_response"]) is not bool
            or type(payload["content"]) is not str
        ):
            raise Refused("demo_request_invalid")
        # Only public synthetic samples, never an unrestricted experience form.
        texts = payload["content"].split("\r\n")
        if not 1 <= len(texts) <= 5 or any(t not in SAMPLES for t in texts):
            raise Refused("demo_synthetic_samples_only")
        # Version from a SELECT-only snapshot, actual write rechecks its lock.
        with self.x.model.connect("reader", True) as db:
            revision = db.execute(
                "SELECT revision FROM ref_sessions WHERE id=%s", (self.b.sid,)
            ).fetchone()["revision"]
        body = command(
            self.b.sid,
            self.b.pid,
            texts,
            revision=revision,
            kind=payload["kind"],
            stage=payload["stage"],
        )
        # Stable selection IDs/body across same-key replay; scoped in server
        # memory for this one demo. Losing this process is outside its recovery.
        with self.lock:
            old = getattr(self, "request", None)
            if old:
                if old[0] != key or old[1] != {
                    k: v for k, v in payload.items() if k != "lose_response"
                }:
                    raise Refused("demo_single_operation_or_payload_conflict")
                body = old[2]
        try:
            with self.x.model.connect() as db:
                submit(db, self.x.gate, self.b, key, body, issuer=self)
        except Refused as exc:
            raise NotSaved(str(exc)) from None
        self.request = (
            key,
            {k: v for k, v in payload.items() if k != "lose_response"},
            body,
        )
        return self.recover(key)

    def recover(self, key):
        with self.x.model.connect("reader", True) as db:
            result = read(db, self.x.gate, self.b, key)
            projected = project(db, self.b.sid, self.b.token, key)
        return dict(
            demo_contract="g4-disposable-read-v1",
            scope="DISPOSABLE_RESEARCH_DATABASE",
            operation_id=result["operation_id"],
            result="committed_pending_review",
            truth_verified=False,
            persistence_authorized=False,
            facts=projected.view,
        )

    def close(self):
        self.signer.close()


def server_for(demo, port=0, assets=None):
    assets = assets or Path(__file__).with_name("web") / "dist"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # no body/key/cookie/SQL logging

        def respond(self, status, value):
            data = json.dumps(value, ensure_ascii=False, default=str).encode("utf8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def admitted(self, *, write=False):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != host:
                return False
            if write and self.headers.get("Origin") != "http://" + host:
                return False
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except Exception:
                return False
            return "g4_demo" in cookie and secrets.compare_digest(
                cookie["g4_demo"].value, demo.cookie
            )

        def do_GET(self):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != host:
                return self.respond(403, dict(code="demo_origin_required"))
            if self.path == "/recover":
                if not self.admitted():
                    return self.respond(401, dict(code="demo_session_required"))
                try:
                    key = str(UUID(self.headers.get("X-Research-Key", "")))
                    return self.respond(200, demo.recover(key))
                except (Refused, ValueError, DatabaseError):
                    return self.respond(409, dict(code="demo_recovery_unavailable"))
            target = (
                assets / "index.html"
                if self.path == "/"
                else assets / self.path.lstrip("/")
            )
            if (
                "?" in self.path
                or target.resolve().parent != assets.resolve()
                and assets.resolve() not in target.resolve().parents
            ):
                return self.respond(404, dict(code="demo_not_found"))
            if not target.is_file():
                return self.respond(404, dict(code="demo_not_found"))
            data = target.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                (
                    "text/html; charset=utf-8"
                    if target.suffix == ".html"
                    else "text/javascript" if target.suffix == ".js" else "text/css"
                ),
            )
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            if self.path == "/":
                self.send_header(
                    "Set-Cookie",
                    f"g4_demo={demo.cookie}; HttpOnly; SameSite=Strict; Path=/",
                )
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/candidate":
                return self.respond(404, dict(code="demo_not_found"))
            if not self.admitted(write=True):
                return self.respond(403, dict(code="demo_origin_required"))
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 20000:
                    raise ValueError()
                key = str(UUID(self.headers.get("X-Research-Key", "")))
                payload = json.loads(self.rfile.read(size))
                result = demo.save(key, payload)
                if payload["lose_response"]:
                    self.close_connection = True
                    return  # actual COMMIT, no HTTP result
                return self.respond(201, result)
            except (ValueError, TypeError, KeyError):
                return self.respond(422, dict(code="demo_request_invalid"))
            except NotSaved as exc:
                status = 503 if str(exc) == "trusted_validator_unavailable" else 409
                return self.respond(status, dict(code="demo_not_saved"))
            except Refused:
                return self.respond(409, dict(code="demo_result_unknown"))
            except DatabaseError:
                return self.respond(503, dict(code="demo_database_unavailable"))

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(
        description="Synthetic disposable research DB only; not Pathwise/CO3"
    )
    parser.add_argument("--synthetic-disposable", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=18174)
    args = parser.parse_args()
    with provision() as x:
        demo = Demo(x)
        server = server_for(demo, args.port)

        def control():
            for line in sys.stdin:
                if line.strip() == "STOP":
                    server.shutdown()
                    return
                if line.strip() == "EVIDENCE":
                    rows = x.model.snapshot()
                    digest = hashlib.sha256(
                        json.dumps(rows, sort_keys=True, default=str).encode()
                    ).hexdigest()
                    print(
                        json.dumps(
                            dict(
                                evidence=digest,
                                facts=len(rows["ref_facts"]),
                                permits=len(rows["g4_permits"]),
                            )
                        ),
                        flush=True,
                    )

        Thread(target=control, daemon=True).start()
        print(
            json.dumps(
                dict(
                    ready=f"http://127.0.0.1:{server.server_port}",
                    scope="SYNTHETIC_DISPOSABLE_NO_FORMAL_CO3",
                )
            ),
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            demo.close()


if __name__ == "__main__":
    main()
