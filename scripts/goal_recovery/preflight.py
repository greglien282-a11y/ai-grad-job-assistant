"""Default-disabled recovery research. Never starts a model turn or a scheduler.

The real adapter only reads Git and an ALREADY RUNNING shared Codex daemon.
An unreachable daemon is unknown, never evidence that a task has stopped.
No authentication files, model prompt, private response or raw error is logged.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time

CONTRACT = "goal-recovery-preflight-v1"
CLI_VERSION = "codex-cli 0.162.0-alpha.17.2"
CHECKPOINT = "docs/goal/GOAL_STATE.md"
STATES = {"ACTIVE", "RATE_LIMITED", "PAUSED", "COMPLETE", "APPROVAL_BLOCKED", "BLOCKED"}
READ_METHODS = {"initialize", "thread/read", "thread/goal/get", "account/read", "account/rateLimits/read"}


class Unavailable(Exception):
    """Fixed code only; never expose raw transport/authentication output."""


def checkpoint_from_text(source: str) -> dict:
    blocks = re.findall(r"```json\s*\n(.*?)\n```", source, re.S)
    if len(blocks) != 1:
        raise Unavailable("CHECKPOINT_INVALID")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Unavailable("CHECKPOINT_INVALID")
            result[key] = value
        return result
    try:
        obj = json.loads(blocks[0], object_pairs_hook=unique)
        if (type(obj) is not dict or set(obj) != {
            "contract", "state", "enabled", "thread_id", "branch", "checkpoint_parent_head",
            "last_successful_commit", "current_subtask", "next_instruction", "blockers",
            "scheduler_approval", "not_before_utc", "last_attempt_id"
        } or obj["contract"] != CONTRACT or obj["state"] not in STATES or obj["enabled"] is not False
            or obj["scheduler_approval"] != "NOT_APPROVED"
            or not re.fullmatch(r"[0-9a-f-]{36}", obj["thread_id"])
            or not re.fullmatch(r"[0-9a-f]{40}", obj["checkpoint_parent_head"])
            or not re.fullmatch(r"[0-9a-f]{40}", obj["last_successful_commit"])
            or type(obj["branch"]) is not str or not obj["branch"].startswith("codex/")
            or type(obj["not_before_utc"]) is not int or obj["not_before_utc"] < 0
            or type(obj["blockers"]) is not list or not all(type(x) is str for x in obj["blockers"])
            or not all(type(obj[k]) is str for k in ("current_subtask", "next_instruction", "last_attempt_id"))):
            raise Unavailable("CHECKPOINT_INVALID")
    except (ValueError, TypeError, KeyError):
        raise Unavailable("CHECKPOINT_INVALID") from None
    return obj


def command(argv: list[str], root: Path) -> str:
    # No shell interpolation, no console windows, no inherited stdin.
    try:
        r = subprocess.run(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True, encoding="utf-8", timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode:
            raise Unavailable("LOCAL_COMMAND_UNAVAILABLE")
        return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        raise Unavailable("LOCAL_COMMAND_UNAVAILABLE") from None


def git_observation(root: Path, cp: dict) -> dict:
    def git(*args):
        return command(["git", "--no-optional-locks", *args], root)
    actual = Path(git("rev-parse", "--show-toplevel")).resolve()
    if actual != root.resolve():
        raise Unavailable("WORKSPACE_MISMATCH")
    head = git("rev-parse", "HEAD")
    anchor = git("log", "-1", "--format=%H", "--", CHECKPOINT)
    parent = git("rev-parse", anchor + "^") if anchor else ""
    committed = git("show", f"HEAD:{CHECKPOINT}") if anchor else ""
    remote = git("remote", "get-url", "origin")
    return {
        "clean": not bool(git("status", "--porcelain=v1", "--untracked-files=all")),
        "head": head, "checkpoint_commit": anchor,
        "matches": (head == anchor and parent == cp["checkpoint_parent_head"]
                    and checkpoint_from_text(committed) == cp
                    and git("branch", "--show-current") == cp["branch"]
                    and remote in {
                        "https://github.com/greglien282-a11y/ai-grad-job-assistant.git",
                        "git@github.com:greglien282-a11y/ai-grad-job-assistant.git"}),
    }


class SharedReadClient:
    """Whitelisted metadata reads through existing daemon only. No fallback server."""
    def __init__(self, executable: str, root: Path):
        self.root, self.executable = root, executable
        self.messages: queue.Queue = queue.Queue()
        self.process = None
        self.seq = 0

    def __enter__(self):
        try:
            self.process = subprocess.Popen(
                [self.executable, "app-server", "proxy"], cwd=self.root,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            raise Unavailable("SHARED_RUNTIME_UNAVAILABLE") from None
        def receive():
            try:
                for line in self.process.stdout:
                    try:
                        self.messages.put(json.loads(line))
                    except ValueError:
                        self.messages.put(None)
            finally:
                self.messages.put(None)
        threading.Thread(target=receive, daemon=True).start()
        try:
            self.request("initialize", {"clientInfo": {"name": "pathwise_readonly_preflight",
                "version": "1"}, "capabilities": {"experimentalApi": False}})
            self.process.stdin.write('{"method":"initialized"}\n')
            self.process.stdin.flush()
        except (Unavailable, OSError):
            self.__exit__(None, None, None)
            raise Unavailable("SHARED_RUNTIME_UNAVAILABLE") from None
        return self

    def request(self, method: str, params: dict) -> dict:
        if method not in READ_METHODS:
            raise Unavailable("METHOD_FORBIDDEN")
        self.seq += 1
        try:
            self.process.stdin.write(json.dumps({"id": self.seq, "method": method, "params": params}) + "\n")
            self.process.stdin.flush()
            deadline = time.monotonic() + 10
            while True:
                msg = self.messages.get(timeout=max(0.001, deadline - time.monotonic()))
                if msg is None or time.monotonic() > deadline:
                    raise Unavailable("SHARED_RUNTIME_UNAVAILABLE")
                if msg.get("id") != self.seq:
                    continue
                if "error" in msg or type(msg.get("result")) is not dict:
                    raise Unavailable("READ_RESPONSE_UNAVAILABLE")
                return msg["result"]
        except (OSError, queue.Empty, AttributeError):
            raise Unavailable("SHARED_RUNTIME_UNAVAILABLE") from None

    def __exit__(self, *_):
        if self.process:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()  # Only our stdio proxy, NEVER the daemon/worker.
                self.process.wait(timeout=2)
            self.process.stdout.close()


def limits_observation(raw: dict) -> dict:
    buckets = raw.get("rateLimitsByLimitId")
    bucket = buckets.get("codex") if type(buckets) is dict else raw.get("rateLimits")
    if type(bucket) is not dict:
        raise Unavailable("QUOTA_UNKNOWN")
    windows = []
    for name, duration in (("primary", 300), ("secondary", 10080)):
        w = bucket.get(name)
        if (type(w) is not dict or type(w.get("usedPercent")) not in (int, float)
                or not math.isfinite(w["usedPercent"]) or not 0 <= w["usedPercent"] <= 100
                or type(w.get("windowDurationMins")) is not int or w["windowDurationMins"] != duration
                or type(w.get("resetsAt")) is not int or w["resetsAt"] <= 0):
            raise Unavailable("QUOTA_UNKNOWN")
        windows.append({k: w[k] for k in ("usedPercent", "windowDurationMins", "resetsAt")})
    return {"windows": windows, "blocked": bool(bucket.get("rateLimitReachedType")
            or bucket.get("spendControlReached") or raw.get("ordinaryUsageAllowed") is False),
            "plan": bucket.get("planType")}


def inspect_runtime(root: Path, cp: dict) -> dict:
    exe = shutil.which("codex")
    if not exe or command([exe, "--version"], root) != CLI_VERSION:
        raise Unavailable("CLI_VERSION_UNSUPPORTED")
    # login status alone establishes stored mode, NOT remote credential validity.
    # A successful authenticated live quota read is required as well.
    with SharedReadClient(exe, root) as client:
        thread = client.request("thread/read", {"threadId": cp["thread_id"], "includeTurns": False})["thread"]
        goal = client.request("thread/goal/get", {"threadId": cp["thread_id"]}).get("goal")
        account = client.request("account/read", {"refreshToken": False}).get("account")
        limits = limits_observation(client.request("account/rateLimits/read", {
            "excludeResetCreditDetails": True, "supportsLunaReserve": False}))
        return {"thread_status": thread.get("status", {}).get("type"),
            "thread_id_matches": thread.get("id") == cp["thread_id"],
            "cwd_matches": Path(thread.get("cwd", "")).resolve() == root.resolve(),
            "goal_status": goal.get("status") if type(goal) is dict else None,
            "auth": (type(account) is dict and account.get("type") == "chatgpt"
                     and account.get("planType") == "plus" and limits["plan"] == "plus"),
            "limits": limits, "observed_at": int(time.time())}


@dataclass(frozen=True)
class Decision:
    code: str
    next_check_after: int | None = None
    execution_enabled: bool = False
    model_turn_started: bool = False
    automatic_resume_proven: bool = False


def decide(cp: dict, git: dict, runtime: dict | None, now: int) -> Decision:
    # A persisted status is a veto, never proof that the task is idle or authorized.
    if cp["state"] not in {"ACTIVE", "RATE_LIMITED"}:
        return Decision("CHECKPOINT_" + cp["state"])
    if not git.get("clean") or not git.get("matches"):
        return Decision("WORKSPACE_REVIEW_REQUIRED")
    if cp["not_before_utc"] > now:
        return Decision("BACKOFF", cp["not_before_utc"])
    if runtime is None:
        return Decision("SHARED_RUNTIME_UNAVAILABLE")
    if (type(runtime.get("observed_at")) is not int
            or not 0 <= now - runtime["observed_at"] <= 30):
        return Decision("OBSERVATION_STALE")
    if runtime.get("goal_status") != "active":
        return Decision("GOAL_REQUIRES_MANUAL_ACTION")
    if runtime.get("thread_status") == "active":
        return Decision("ALREADY_RUNNING")
    if (runtime.get("thread_status") != "idle" or not runtime.get("thread_id_matches")
            or not runtime.get("cwd_matches")):
        return Decision("RUNTIME_REVIEW_REQUIRED")
    if runtime.get("auth") is not True:
        return Decision("AUTH_REVIEW_REQUIRED")
    limits = runtime["limits"]
    exhausted = [w for w in limits["windows"] if w["usedPercent"] >= 100]
    if exhausted or limits["blocked"]:
        # Past reset times are NOT evidence that a quota has refreshed.
        return Decision("RATE_LIMITED", max([now + 3600] + [w["resetsAt"] for w in exhausted]))
    if cp["blockers"]:
        return Decision("APPROVAL_OR_BASELINE_BLOCKED")
    # All readable gates could pass, but read-then-exec has a TOCTOU race with
    # desktop Goal continuation. No supported atomic idle lease is established.
    return Decision("DISABLED_ATOMIC_RESUME_UNPROVEN")


def stopped_attempt(event: str, now: int, reset_at: int | None = None) -> dict:
    """Candidate journal policy, exercised synthetically; no actual exec is issued."""
    states = {"rate_limit_429": "RATE_LIMITED", "auth_failed": "APPROVAL_BLOCKED",
              "approval_required": "APPROVAL_BLOCKED", "failed": "BLOCKED",
              "transport_unknown": "BLOCKED", "completed_turn": "ACTIVE"}
    if event not in states:
        raise Unavailable("OUTCOME_UNKNOWN")
    # A completed TURN never marks the full GOAL complete.
    return {"state": states[event], "not_before_utc": max(now + 3600, reset_at or 0),
            "retry_in_this_process": False, "resume_requires_fresh_observation": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--inspect-local", action="store_true",
                        help="read existing shared daemon metadata; no model run or new daemon")
    args = parser.parse_args(argv)
    output = {"contract": CONTRACT, "execution_enabled": False, "model_turns": 0,
              "scheduler_changes": 0, "repository_writes": 0}
    try:
        cp = checkpoint_from_text((args.repo / CHECKPOINT).read_text(encoding="utf-8"))
        git = git_observation(args.repo, cp)
        output["git"] = git
        runtime = None
        if args.inspect_local:
            try:
                runtime = inspect_runtime(args.repo, cp)
            except (Unavailable, KeyError, TypeError, ValueError) as exc:
                output["probe_code"] = str(exc) if isinstance(exc, Unavailable) else "READ_SCHEMA_UNSUPPORTED"
        output["decision"] = asdict(decide(cp, git, runtime, int(time.time())))
        output["mode"] = "READ_ONLY_INSPECTION" if args.inspect_local else "DISABLED"
    except (Unavailable, OSError) as exc:
        output["decision"] = asdict(Decision(str(exc) if isinstance(exc, Unavailable) else "CHECKPOINT_UNAVAILABLE"))
    print(json.dumps(output, sort_keys=True))
    return 0  # Inspection completed; this is NEVER a successful work/Goal result.


if __name__ == "__main__":
    raise SystemExit(main())
