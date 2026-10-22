"""Synthetic policy + real temporary Git checks; no model/daemon/network calls."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import preflight as p


NOW = 1_800_000_000


def checkpoint():
    return {"contract": p.CONTRACT, "state": "ACTIVE", "enabled": False,
        "thread_id": "00000000-0000-4000-8000-000000000001", "branch": "codex/test",
        "checkpoint_parent_head": "a" * 40, "last_successful_commit": "a" * 40,
        "current_subtask": "synthetic", "next_instruction": "inspect only", "blockers": [],
        "scheduler_approval": "NOT_APPROVED", "not_before_utc": 0, "last_attempt_id": "none"}


def window(percent, duration, reset):
    return {"usedPercent": percent, "windowDurationMins": duration, "resetsAt": reset}


def raw_limits():
    return {"ordinaryUsageAllowed": True, "rateLimitsByLimitId": {"codex": {
        "planType": "plus", "primary": window(16, 300, NOW + 100),
        "secondary": window(45, 10080, NOW + 9000), "rateLimitReachedType": None}}}


def runtime():
    return {"thread_status": "idle", "thread_id_matches": True, "cwd_matches": True,
        "goal_status": "active", "auth": True, "observed_at": NOW,
        "limits": p.limits_observation(raw_limits())}


def md(cp):
    return "# Synthetic checkpoint\n\n```json\n" + json.dumps(cp) + "\n```\n"


class PolicyTests(unittest.TestCase):
    def decision(self, cp=None, rt=None, git=None):
        result = p.decide(cp or checkpoint(), git or {"clean": True, "matches": True},
                          rt or runtime(), NOW)
        self.assertFalse(result.execution_enabled)
        self.assertFalse(result.model_turn_started)
        self.assertFalse(result.automatic_resume_proven)
        return result

    def test_all_readable_gates_pass_still_no_live_executor(self):
        self.assertEqual(self.decision().code, "DISABLED_ATOMIC_RESUME_UNPROVEN")

    def test_active_thread_never_restarted(self):
        r = runtime(); r["thread_status"] = "active"
        self.assertEqual(self.decision(rt=r).code, "ALREADY_RUNNING")

    def test_missing_handle_is_unknown_not_stopped(self):
        result = p.decide(checkpoint(), {"clean": True, "matches": True}, None, NOW)
        self.assertEqual(result.code, "SHARED_RUNTIME_UNAVAILABLE")
        self.assertFalse(result.model_turn_started)

    def test_not_loaded_is_not_idle(self):
        r = runtime(); r["thread_status"] = "notLoaded"
        self.assertEqual(self.decision(rt=r).code, "RUNTIME_REVIEW_REQUIRED")

    def test_system_error_is_not_idle(self):
        r = runtime(); r["thread_status"] = "systemError"
        self.assertEqual(self.decision(rt=r).code, "RUNTIME_REVIEW_REQUIRED")

    def test_wrong_thread_id(self):
        r = runtime(); r["thread_id_matches"] = False
        self.assertEqual(self.decision(rt=r).code, "RUNTIME_REVIEW_REQUIRED")

    def test_wrong_runtime_worktree(self):
        r = runtime(); r["cwd_matches"] = False
        self.assertEqual(self.decision(rt=r).code, "RUNTIME_REVIEW_REQUIRED")

    def test_auth_failure_no_api_key_fallback(self):
        r = runtime(); r["auth"] = False
        self.assertEqual(self.decision(rt=r).code, "AUTH_REVIEW_REQUIRED")

    def test_checkpoint_pause_complete_approval_and_blocked_stop(self):
        for status in ("PAUSED", "COMPLETE", "APPROVAL_BLOCKED", "BLOCKED"):
            with self.subTest(status=status):
                cp = checkpoint(); cp["state"] = status
                self.assertEqual(self.decision(cp=cp).code, "CHECKPOINT_" + status)

    def test_authoritative_goal_vetoes_even_stale_active_checkpoint(self):
        for status in ("paused", "complete", "blocked", "usageLimited", "budgetLimited", None):
            with self.subTest(status=status):
                r = runtime(); r["goal_status"] = status
                self.assertEqual(self.decision(rt=r).code, "GOAL_REQUIRES_MANUAL_ACTION")

    def test_stale_and_future_observations(self):
        for timestamp in (NOW - 31, NOW + 1, None, True):
            with self.subTest(timestamp=timestamp):
                r = runtime(); r["observed_at"] = timestamp
                self.assertEqual(self.decision(rt=r).code, "OBSERVATION_STALE")

    def test_dirty_and_head_drift_stop(self):
        for git in ({"clean": False, "matches": True}, {"clean": True, "matches": False}):
            self.assertEqual(self.decision(git=git).code, "WORKSPACE_REVIEW_REQUIRED")

    def test_five_hour_exhausted(self):
        r = runtime(); r["limits"]["windows"][0]["usedPercent"] = 100
        self.assertEqual(self.decision(rt=r).code, "RATE_LIMITED")

    def test_weekly_exhausted_blocks_after_five_hour_reset(self):
        r = runtime(); r["limits"]["windows"][0]["usedPercent"] = 0
        r["limits"]["windows"][1]["usedPercent"] = 100
        self.assertEqual(self.decision(rt=r).next_check_after, NOW + 9000)

    def test_past_reset_time_never_grants_quota(self):
        r = runtime(); r["limits"]["windows"][1].update(usedPercent=100, resetsAt=NOW - 1)
        result = self.decision(rt=r)
        self.assertEqual((result.code, result.next_check_after), ("RATE_LIMITED", NOW + 3600))

    def test_server_block_overrides_small_percent(self):
        r = runtime(); r["limits"]["blocked"] = True
        self.assertEqual(self.decision(rt=r).code, "RATE_LIMITED")

    def test_backoff_does_not_probe_or_retry_work(self):
        cp = checkpoint(); cp["not_before_utc"] = NOW + 500
        self.assertEqual(self.decision(cp=cp).code, "BACKOFF")

    def test_unmerged_baseline_or_approval_block(self):
        cp = checkpoint(); cp["blockers"] = ["PR46_NOT_MERGED"]
        self.assertEqual(self.decision(cp=cp).code, "APPROVAL_OR_BASELINE_BLOCKED")

    def test_429_records_rate_limited_not_complete(self):
        result = p.stopped_attempt("rate_limit_429", NOW, NOW + 9000)
        self.assertEqual(result["state"], "RATE_LIMITED")
        self.assertEqual(result["not_before_utc"], NOW + 9000)
        self.assertFalse(result["retry_in_this_process"])

    def test_other_failures_do_not_retry_or_clear_approval(self):
        for event in ("auth_failed", "approval_required", "failed", "transport_unknown"):
            result = p.stopped_attempt(event, NOW)
            self.assertIn(result["state"], {"BLOCKED", "APPROVAL_BLOCKED"})
            self.assertFalse(result["retry_in_this_process"])

    def test_completed_turn_does_not_complete_goal(self):
        self.assertEqual(p.stopped_attempt("completed_turn", NOW)["state"], "ACTIVE")

    def test_unknown_outcome_rejected(self):
        with self.assertRaises(p.Unavailable): p.stopped_attempt("looks_good", NOW)

    def test_missing_or_malformed_quota_not_zero_usage(self):
        for bad in (None, {}, "missing", {"usedPercent": 0}):
            raw = raw_limits(); raw["rateLimitsByLimitId"]["codex"]["secondary"] = bad
            with self.assertRaises(p.Unavailable): p.limits_observation(raw)
        for value in (True, "0", -1, 101, float("nan"), float("inf")):
            raw = raw_limits(); raw["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = value
            with self.assertRaises(p.Unavailable): p.limits_observation(raw)

    def test_multi_bucket_does_not_fallback_if_codex_missing(self):
        raw = raw_limits(); raw["rateLimits"] = raw["rateLimitsByLimitId"].pop("codex")
        with self.assertRaises(p.Unavailable): p.limits_observation(raw)

    def test_changed_window_contract_requires_review(self):
        raw = raw_limits(); raw["rateLimitsByLimitId"]["codex"]["primary"]["windowDurationMins"] = 60
        with self.assertRaises(p.Unavailable): p.limits_observation(raw)

    def test_enabling_or_extra_shell_field_is_rejected(self):
        for key, value in (("enabled", True), ("command", "anything"), ("scheduler_approval", "APPROVED")):
            cp = checkpoint(); cp[key] = value
            with self.assertRaises(p.Unavailable): p.checkpoint_from_text(md(cp))

    def test_duplicate_checkpoint_keys_and_blocks_rejected(self):
        source = md(checkpoint())
        with self.assertRaises(p.Unavailable): p.checkpoint_from_text(source + source)
        with self.assertRaises(p.Unavailable): p.checkpoint_from_text(source.replace('"enabled": false', '"enabled": false, "enabled": true'))

    def test_whitelist_rejects_every_work_or_account_mutation(self):
        client = p.SharedReadClient("not_started", Path.cwd())
        for method in ("turn/start", "thread/resume", "thread/goal/set", "account/login/start",
                       "account/rateLimitResetCredit/consume", "account/sendAddCreditsNudgeEmail"):
            with self.assertRaisesRegex(p.Unavailable, "METHOD_FORBIDDEN"):
                client.request(method, {})

    def test_proxy_failure_has_no_fallback_or_sensitive_errors(self):
        with patch.object(p.subprocess, "Popen", side_effect=OSError("SECRET-DO-NOT-LOG")) as proc:
            with self.assertRaisesRegex(p.Unavailable, "^SHARED_RUNTIME_UNAVAILABLE$"):
                with p.SharedReadClient("codex", Path.cwd()): pass
        self.assertEqual(proc.call_count, 1)
        self.assertEqual(proc.call_args.args[0], ["codex", "app-server", "proxy"])


class RealGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.git("init", "-b", "codex/test")
        self.git("config", "user.name", "Synthetic")
        self.git("config", "user.email", "synthetic@invalid")
        self.git("remote", "add", "origin", "https://github.com/greglien282-a11y/ai-grad-job-assistant.git")
        (self.root / "base.txt").write_text("synthetic\n")
        self.git("add", "base.txt"); self.git("commit", "-m", "base")
        self.cp = checkpoint(); self.cp["checkpoint_parent_head"] = self.git("rev-parse", "HEAD")
        path = self.root / p.CHECKPOINT; path.parent.mkdir(parents=True)
        path.write_text(md(self.cp), encoding="utf-8")
        self.git("add", p.CHECKPOINT); self.git("commit", "-m", "checkpoint")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.DEVNULL,
                                       text=True, encoding="utf-8").strip()

    def test_clean_anchor_then_untracked_then_uncheckpointed_commit(self):
        obs = p.git_observation(self.root, self.cp)
        self.assertTrue(obs["clean"] and obs["matches"])
        (self.root / "extra.txt").write_text("synthetic")
        self.assertFalse(p.git_observation(self.root, self.cp)["clean"])
        self.git("add", "extra.txt"); self.git("commit", "-m", "drift")
        obs = p.git_observation(self.root, self.cp)
        self.assertTrue(obs["clean"]); self.assertFalse(obs["matches"])

    def test_wrong_parent_or_branch_cannot_pass(self):
        cp = copy.deepcopy(self.cp); cp["checkpoint_parent_head"] = "b" * 40
        self.assertFalse(p.git_observation(self.root, cp)["matches"])
        self.git("switch", "-c", "codex/other")
        self.assertFalse(p.git_observation(self.root, self.cp)["matches"])

    def test_default_rehearsal_has_no_daemon_model_or_git_effect(self):
        before = (self.git("rev-parse", "HEAD"), self.git("status", "--porcelain=v1"),
                  (self.root / p.CHECKPOINT).read_bytes())
        out = io.StringIO()
        with patch.object(p, "inspect_runtime", side_effect=AssertionError("no probe")), contextlib.redirect_stdout(out):
            self.assertEqual(p.main(["--repo", str(self.root)]), 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["mode"], "DISABLED")
        self.assertEqual(result["model_turns"], 0)
        self.assertEqual(result["repository_writes"], 0)
        self.assertEqual(before, (self.git("rev-parse", "HEAD"), self.git("status", "--porcelain=v1"),
                                 (self.root / p.CHECKPOINT).read_bytes()))

    def test_failed_live_probe_is_single_attempt_without_raw_error(self):
        out = io.StringIO()
        with patch.object(p, "inspect_runtime", side_effect=p.Unavailable("SHARED_RUNTIME_UNAVAILABLE")) as probe, contextlib.redirect_stdout(out):
            p.main(["--repo", str(self.root), "--inspect-local"])
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(json.loads(out.getvalue())["probe_code"], "SHARED_RUNTIME_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
