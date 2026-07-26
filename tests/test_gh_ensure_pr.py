from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
GH_SCRIPTS = ROOT / "skills" / "ceratops-gh-repo-lifecycle" / "scripts"
sys.path.insert(0, str(GH_SCRIPTS))

from github_pr_workflow import (  # noqa: E402
    dependency_finalization,
    ensure_pr,
    merge,
    ship,
)


class EnsurePrTests(unittest.TestCase):
    def args(self) -> argparse.Namespace:
        return argparse.Namespace(head_branch="release/local")

    def test_waits_until_github_reports_the_pushed_head(self) -> None:
        responses = [
            {"headRefOid": "old"},
            {"headRefOid": "old"},
            {"headRefOid": "new"},
        ]
        with mock.patch.object(ensure_pr, "_open_pr", side_effect=responses) as probe:
            result = ensure_pr.wait_for_pr_head(
                self.args(), "new", max_attempts=4, delay_seconds=0
            )

        self.assertEqual(result["headRefOid"], "new")
        self.assertEqual(probe.call_count, 3)

    def test_stops_after_the_bounded_attempt_count(self) -> None:
        with mock.patch.object(
            ensure_pr, "_open_pr", return_value={"headRefOid": "old"}
        ) as probe:
            with self.assertRaisesRegex(ensure_pr.EnsurePrError, "after 3 attempts"):
                ensure_pr.wait_for_pr_head(
                    self.args(), "new", max_attempts=3, delay_seconds=0
                )

        self.assertEqual(probe.call_count, 3)


class ShipTests(unittest.TestCase):
    commit = "a" * 40

    def args(self, repo_root: pathlib.Path) -> argparse.Namespace:
        return argparse.Namespace(
            repo_root=repo_root,
            repo="owner/repo",
            head_branch="release/local",
            base_branch="main",
            remote_name="origin",
            commit=None,
            title=None,
            body=None,
            merge_method="merge",
            admin=False,
            delete_branch=False,
            reusable_head=True,
            ci_wait_seconds=30,
            review_wait_seconds=30,
            interval_seconds=0,
        )

    def test_passing_mergeability_is_not_treated_as_pending(self) -> None:
        findings = [
            ship.readiness.Finding(
                level="PASS",
                check="pr.mergeable",
                message="PR is mergeable.",
                actual="MERGEABLE",
            )
        ]
        with mock.patch.object(
            ship.readiness,
            "validate_readiness",
            return_value=({"head_oid": self.commit, "number": 17}, findings),
        ) as validate:
            result = ship.wait_for_ci_gate(
                "17",
                pathlib.Path.cwd(),
                self.commit,
                wait_seconds=0,
                interval_seconds=0,
            )

        self.assertEqual(result["pending"], 0)
        validate.assert_called_once()
        self.assertTrue(
            validate.call_args.kwargs["allow_admin_review_bypass"]
        )

    def test_no_attached_checks_remain_pending(self) -> None:
        finding = ship.readiness.Finding(
            level="WARN",
            check="pr.status_checks",
            message="No status checks are attached to this PR.",
        )

        self.assertTrue(ship._transient_readiness(finding))

    def test_admin_review_bypass_is_not_treated_as_pending(self) -> None:
        bypassed = ship.readiness.Finding(
            level="WARN",
            check="pr.review_decision",
            message="Required review is bypassable.",
            actual="REVIEW_REQUIRED",
        )
        blocking = ship.readiness.Finding(
            level="ERROR",
            check="pr.review_decision",
            message="PR still requires review.",
            actual="REVIEW_REQUIRED",
        )

        self.assertFalse(ship._transient_readiness(bypassed))
        self.assertTrue(ship._transient_readiness(blocking))
        with mock.patch.object(
            ship.readiness,
            "validate_readiness",
            return_value=(
                {"head_oid": self.commit, "number": 17},
                [bypassed],
            ),
        ):
            result = ship.wait_for_ci_gate(
                "17",
                pathlib.Path.cwd(),
                self.commit,
                wait_seconds=0,
                interval_seconds=0,
            )

        self.assertTrue(result["review_authorization_required"])

    def test_codex_review_window_starts_with_the_current_invocation(self) -> None:
        created_at = "2000-01-01T00:00:00Z"
        pr_data = {
            "number": 17,
            "url": "https://example.test/pr/17",
            "createdAt": created_at,
            "headRefOid": self.commit,
            "reviewThreads": [],
        }
        with mock.patch.object(
            ship.codex_review, "fetch_pr", return_value=pr_data
        ) as fetch:
            result = ship.codex_review.wait_for_codex_threads(
                "17",
                "owner/repo",
                wait_seconds=0,
                interval_seconds=0,
                authors=ship.codex_review.DEFAULT_CODEX_AUTHORS,
                cwd=pathlib.Path.cwd(),
            )

        self.assertGreater(
            ship.codex_review.parse_utc(result["deadline"]),
            ship.codex_review.parse_utc(created_at),
        )
        fetch.assert_called_once()

    def test_parallel_gates_start_together(self) -> None:
        barrier = threading.Barrier(2)

        def ci_gate(*args, **kwargs):
            barrier.wait(timeout=2)
            return {
                "head_oid": self.commit,
                "review_authorization_required": False,
            }

        def review_gate(*args, **kwargs):
            barrier.wait(timeout=2)
            return {
                "head_oid": self.commit,
                "active_codex_thread_count": 0,
            }

        args = self.args(pathlib.Path.cwd())
        with (
            mock.patch.object(ship, "wait_for_ci_gate", side_effect=ci_gate),
            mock.patch.object(
                ship.codex_review,
                "wait_for_codex_threads",
                side_effect=review_gate,
            ),
        ):
            result = ship.run_parallel_gates(
                args,
                "17",
                "owner/repo",
                self.commit,
                ci_wait_seconds=0,
                review_wait_seconds=0,
            )

        self.assertEqual(result["ci"]["head_oid"], self.commit)
        self.assertEqual(result["codex"]["active_threads"], 0)
        self.assertEqual(result["disposition"], "passed")

    def test_parallel_gates_preflight_required_unresolved_threads(self) -> None:
        args = self.args(pathlib.Path.cwd())
        preflight = {
            "head_oid": self.commit,
            "active_codex_thread_count": 0,
            "active_codex_threads": [],
            "unresolved_review_thread_count": 2,
            "unresolved_review_threads": [
                {"id": "PRRT_old_1", "is_outdated": True},
                {"id": "PRRT_old_2", "is_outdated": True},
            ],
        }
        with (
            mock.patch.object(
                ship.codex_review,
                "wait_for_codex_threads",
                return_value=preflight,
            ) as review_wait,
            mock.patch.object(ship, "wait_for_ci_gate") as ci_wait,
            mock.patch.object(
                ship.readiness,
                "review_thread_resolution_required",
                return_value=True,
            ) as resolution_required,
        ):
            with self.assertRaisesRegex(
                ship.ShipError,
                "PRRT_old_1, PRRT_old_2",
            ):
                ship.run_parallel_gates(
                    args,
                    "17",
                    "owner/repo",
                    self.commit,
                    ci_wait_seconds=30,
                    review_wait_seconds=30,
                )

        review_wait.assert_called_once()
        self.assertEqual(review_wait.call_args.kwargs["wait_seconds"], 0)
        resolution_required.assert_called_once_with("main", args.repo_root)
        ci_wait.assert_not_called()

    def test_parallel_gates_enforce_required_thread_resolution(self) -> None:
        args = self.args(pathlib.Path.cwd())
        with (
            mock.patch.object(
                ship,
                "wait_for_ci_gate",
                return_value={
                    "base": "main",
                    "head_oid": self.commit,
                    "review_authorization_required": False,
                },
            ),
            mock.patch.object(
                ship.codex_review,
                "wait_for_codex_threads",
                return_value={
                    "head_oid": self.commit,
                    "active_codex_thread_count": 0,
                    "unresolved_review_thread_count": 2,
                },
            ),
            mock.patch.object(
                ship.readiness,
                "review_thread_resolution_required",
                return_value=True,
            ) as resolution_required,
        ):
            with self.assertRaisesRegex(
                ship.ShipError,
                "require resolution of 2 unresolved review thread",
            ):
                ship.run_parallel_gates(
                    args,
                    "17",
                    "owner/repo",
                    self.commit,
                    ci_wait_seconds=0,
                    review_wait_seconds=0,
                )

        resolution_required.assert_called_once_with("main", args.repo_root)

    def test_ship_removes_only_completed_same_pr_checkpoints(self) -> None:
        state = {
            "version": 1,
            "repository": "owner/repo",
            "commit": self.commit,
            "head_branch": "release/local",
            "base_branch": "main",
            "phase": "prepared",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = pathlib.Path(temporary_directory)
            args = self.args(repo_root)
            checkpoint = repo_root / "checkpoint.json"
            checkpoint.write_text("checkpoint", encoding="utf-8")
            same_pr_checkpoint = repo_root / "same-pr.json"
            same_pr_checkpoint.write_text(
                json.dumps(
                    {
                        **state,
                        "commit": "c" * 40,
                        "phase": "pr_ready",
                        "pr": 17,
                    }
                ),
                encoding="utf-8",
            )
            unrelated_checkpoint = repo_root / "unrelated.json"
            unrelated_checkpoint.write_text(
                json.dumps(
                    {
                        **state,
                        "commit": "d" * 40,
                        "phase": "pr_ready",
                        "pr": 99,
                    }
                ),
                encoding="utf-8",
            )
            unidentifiable_checkpoint = repo_root / "unidentifiable.json"
            unidentifiable_checkpoint.write_text("invalid", encoding="utf-8")
            with (
                mock.patch.object(
                    ship, "_repository_name", return_value="owner/repo"
                ),
                mock.patch.object(ship, "_resolve_commit", return_value=self.commit),
                mock.patch.object(
                    ship,
                    "_load_or_create_checkpoint",
                    return_value=(checkpoint, state),
                ),
                mock.patch.object(ship, "_write_checkpoint"),
                mock.patch.object(
                    ship.ensure_pr,
                    "ensure_pr",
                    return_value={
                        "pr": 17,
                        "url": "https://example.test/pr/17",
                    },
                ) as ensure,
                mock.patch.object(
                    ship,
                    "_live_pr",
                    return_value={
                        "state": "OPEN",
                        "headRefOid": self.commit,
                    },
                ),
                mock.patch.object(
                    ship,
                    "run_parallel_gates",
                    return_value={
                        "disposition": "passed",
                        "authorization_required": False,
                    },
                ) as gates,
                mock.patch.object(
                    ship.merge,
                    "merge_verified_pr",
                    return_value={
                        "status": "merged",
                        "merged_at": "2026-07-25T00:00:00Z",
                        "merge_commit": "b" * 40,
                    },
                ) as merge_pr,
                mock.patch.object(
                    ship.sync,
                    "sync_main",
                    return_value={"head": "b" * 40},
                ) as sync_main,
                mock.patch.object(
                    ship,
                    "restore_reusable_branch",
                    return_value={
                        "branch": "release/local",
                        "status": "restored",
                        "head": "b" * 40,
                    },
                ),
            ):
                result = ship.ship(args)
            checkpoint_removed = not checkpoint.exists()
            same_pr_removed = not same_pr_checkpoint.exists()
            unrelated_retained = unrelated_checkpoint.exists()
            unidentifiable_retained = unidentifiable_checkpoint.exists()

        self.assertEqual(result["status"], "shipped")
        self.assertEqual(
            result["changes"],
            [
                "pr_ready",
                "gates_passed",
                "merged",
                "reusable_branch_restored",
                "synchronized",
            ],
        )
        self.assertTrue(checkpoint_removed)
        self.assertTrue(same_pr_removed)
        self.assertTrue(unrelated_retained)
        self.assertTrue(unidentifiable_retained)
        self.assertEqual(result["removed_checkpoints"], 2)
        ensure.assert_called_once()
        self.assertEqual(gates.call_count, 2)
        merge_pr.assert_called_once()
        self.assertEqual(merge_pr.call_args.args[0].wait_seconds, 0)
        sync_main.assert_called_once()

    def test_ship_returns_exact_authorization_handoff_after_gates(self) -> None:
        state = {
            "version": 1,
            "repository": "owner/repo",
            "commit": self.commit,
            "head_branch": "release/local",
            "base_branch": "main",
            "phase": "pr_ready",
            "pr": 17,
            "url": "https://example.test/pr/17",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = pathlib.Path(temporary_directory)
            args = self.args(repo_root)
            checkpoint = repo_root / "checkpoint.json"
            checkpoint.write_text("checkpoint", encoding="utf-8")
            with (
                mock.patch.object(
                    ship, "_repository_name", return_value="owner/repo"
                ),
                mock.patch.object(ship, "_resolve_commit", return_value=self.commit),
                mock.patch.object(
                    ship,
                    "_load_or_create_checkpoint",
                    return_value=(checkpoint, state),
                ),
                mock.patch.object(ship, "_write_checkpoint") as write_checkpoint,
                mock.patch.object(
                    ship,
                    "_live_pr",
                    return_value={
                        "state": "OPEN",
                        "headRefOid": self.commit,
                    },
                ),
                mock.patch.object(
                    ship,
                    "run_parallel_gates",
                    return_value={
                        "disposition": "authorization_required",
                        "authorization_required": True,
                    },
                ) as gates,
                mock.patch.object(ship.merge, "merge_verified_pr") as merge_pr,
                mock.patch.object(ship.sync, "sync_main") as sync_main,
            ):
                result = ship.ship(args)
            checkpoint_retained = checkpoint.exists()

        self.assertEqual(result["status"], "authorization_required")
        self.assertEqual(result["phase"], "gates_passed")
        self.assertTrue(result["authorization_required"])
        self.assertEqual(result["next_cwd"], str(pathlib.Path.cwd().resolve()))
        self.assertIn("--admin", result["next_argv"])
        self.assertEqual(
            result["next_argv"][result["next_argv"].index("--commit") + 1],
            self.commit,
        )
        self.assertEqual(gates.call_count, 2)
        self.assertTrue(checkpoint_retained)
        write_checkpoint.assert_called_once()
        merge_pr.assert_not_called()
        sync_main.assert_not_called()

    def test_authorized_resume_rechecks_once_then_completes(self) -> None:
        merge_commit = "b" * 40
        state = {
            "version": 1,
            "repository": "owner/repo",
            "commit": self.commit,
            "head_branch": "release/local",
            "base_branch": "main",
            "phase": "gates_passed",
            "pr": 17,
            "url": "https://example.test/pr/17",
            "gate_disposition": "authorization_required",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = pathlib.Path(temporary_directory)
            args = self.args(repo_root)
            args.admin = True
            checkpoint = repo_root / "checkpoint.json"
            checkpoint.write_text("checkpoint", encoding="utf-8")
            with (
                mock.patch.object(
                    ship, "_repository_name", return_value="owner/repo"
                ),
                mock.patch.object(ship, "_resolve_commit", return_value=self.commit),
                mock.patch.object(
                    ship,
                    "_load_or_create_checkpoint",
                    return_value=(checkpoint, state),
                ),
                mock.patch.object(ship, "_write_checkpoint"),
                mock.patch.object(
                    ship,
                    "_live_pr",
                    return_value={
                        "state": "OPEN",
                        "headRefOid": self.commit,
                    },
                ),
                mock.patch.object(
                    ship,
                    "run_parallel_gates",
                    return_value={
                        "disposition": "admin_authorized",
                        "authorization_required": False,
                    },
                ) as gates,
                mock.patch.object(
                    ship.merge,
                    "merge_verified_pr",
                    return_value={
                        "status": "merged",
                        "merged_at": "2026-07-25T00:00:00Z",
                        "merge_commit": merge_commit,
                    },
                ) as merge_pr,
                mock.patch.object(
                    ship.sync,
                    "sync_main",
                    return_value={"head": merge_commit},
                ),
                mock.patch.object(
                    ship,
                    "restore_reusable_branch",
                    return_value={
                        "branch": "release/local",
                        "status": "aligned",
                        "head": merge_commit,
                    },
                ),
            ):
                result = ship.ship(args)

        self.assertEqual(result["status"], "shipped")
        self.assertEqual(result["phase"], "synchronized")
        self.assertEqual(result["gate_disposition"], "admin_authorized")
        self.assertFalse(result["authorization_required"])
        gates.assert_called_once()
        merge_pr.assert_called_once()
        self.assertTrue(merge_pr.call_args.args[0].admin)

    def test_ship_retains_checkpoint_when_a_gate_fails(self) -> None:
        state = {
            "version": 1,
            "repository": "owner/repo",
            "commit": self.commit,
            "head_branch": "release/local",
            "base_branch": "main",
            "phase": "pr_ready",
            "pr": 17,
            "url": "https://example.test/pr/17",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = pathlib.Path(temporary_directory)
            args = self.args(repo_root)
            checkpoint = repo_root / "checkpoint.json"
            checkpoint.write_text("checkpoint", encoding="utf-8")
            with (
                mock.patch.object(
                    ship, "_repository_name", return_value="owner/repo"
                ),
                mock.patch.object(ship, "_resolve_commit", return_value=self.commit),
                mock.patch.object(
                    ship,
                    "_load_or_create_checkpoint",
                    return_value=(checkpoint, state),
                ),
                mock.patch.object(
                    ship,
                    "_live_pr",
                    return_value={
                        "state": "OPEN",
                        "headRefOid": self.commit,
                    },
                ),
                mock.patch.object(
                    ship,
                    "run_parallel_gates",
                    side_effect=ship.ShipError("gate failed"),
                ),
            ):
                with self.assertRaisesRegex(ship.ShipError, "gate failed"):
                    ship.ship(args)

            self.assertTrue(checkpoint.exists())

    def test_missing_completed_checkpoint_reconciles_exact_merged_pr(self) -> None:
        merge_commit = "b" * 40
        api_result = mock.Mock(
            ok=True,
            data=[
                {
                    "number": 17,
                    "url": "https://example.test/pr/17",
                    "state": "MERGED",
                    "headRefOid": self.commit,
                    "baseRefName": "main",
                    "mergedAt": "2026-07-25T00:00:00Z",
                    "mergeCommit": {"oid": merge_commit},
                },
                {
                    "number": 16,
                    "url": "https://example.test/pr/16",
                    "state": "MERGED",
                    "headRefOid": "c" * 40,
                    "baseRefName": "main",
                    "mergedAt": "2026-07-24T00:00:00Z",
                    "mergeCommit": {"oid": "d" * 40},
                },
            ],
            message=None,
            status=200,
        )
        args = self.args(pathlib.Path.cwd())
        with mock.patch.object(
            ship, "run_json_command", return_value=api_result
        ) as lookup:
            state = ship._merged_pr_checkpoint(
                args,
                pathlib.Path.cwd(),
                "owner/repo",
                self.commit,
            )

        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state["phase"], "merged")
        self.assertEqual(state["pr"], 17)
        self.assertEqual(state["merge_commit"], merge_commit)
        command = lookup.call_args.args[0]
        self.assertIn("pr", command)
        self.assertIn("list", command)
        self.assertIn(self.commit, str(api_result.data))

    def test_completed_retry_reconciles_syncs_and_removes_checkpoint(self) -> None:
        merge_commit = "b" * 40
        merged_state = {
            "version": 1,
            "repository": "owner/repo",
            "commit": self.commit,
            "head_branch": "release/local",
            "base_branch": "main",
            "phase": "merged",
            "pr": 17,
            "url": "https://example.test/pr/17",
            "merged_at": "2026-07-25T00:00:00Z",
            "merge_commit": merge_commit,
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo_root = pathlib.Path(temporary_directory)
            args = self.args(repo_root)
            checkpoint = repo_root / "checkpoint.json"
            with (
                mock.patch.object(
                    ship, "_repository_name", return_value="owner/repo"
                ),
                mock.patch.object(ship, "_resolve_commit", return_value=self.commit),
                mock.patch.object(
                    ship, "_checkpoint_path", return_value=checkpoint
                ),
                mock.patch.object(
                    ship,
                    "_new_checkpoint",
                    side_effect=ship.ShipError(
                        "checkout is no longer on the shipped head"
                    ),
                ),
                mock.patch.object(
                    ship,
                    "_merged_pr_checkpoint",
                    return_value=merged_state,
                ) as reconcile,
                mock.patch.object(ship.ensure_pr, "ensure_pr") as ensure,
                mock.patch.object(ship, "run_parallel_gates") as gates,
                mock.patch.object(ship.merge, "merge_verified_pr") as merge_pr,
                mock.patch.object(
                    ship.sync,
                    "sync_main",
                    return_value={"head": merge_commit},
                ) as sync_main,
                mock.patch.object(
                    ship,
                    "restore_reusable_branch",
                    return_value={
                        "branch": "release/local",
                        "status": "aligned",
                        "head": merge_commit,
                    },
                ),
            ):
                result = ship.ship(args)
            checkpoint_removed = not checkpoint.exists()

        self.assertEqual(result["status"], "shipped")
        self.assertEqual(
            result["changes"], ["reusable_branch_aligned", "synchronized"]
        )
        self.assertTrue(checkpoint_removed)
        reconcile.assert_called_once_with(
            args, repo_root, "owner/repo", self.commit
        )
        ensure.assert_not_called()
        gates.assert_not_called()
        merge_pr.assert_not_called()
        sync_main.assert_called_once()

    def test_deleted_reusable_remote_branch_is_restored(self) -> None:
        with (
            mock.patch.object(ship, "require_output", return_value="b" * 40),
            mock.patch.object(ship, "_remote_head", return_value=None),
            mock.patch.object(ship, "require_success") as push,
        ):
            result = ship.restore_reusable_branch(
                pathlib.Path.cwd(),
                remote_name="origin",
                branch="release/local",
                shipped_commit=self.commit,
                synchronized_head="b" * 40,
            )

        self.assertEqual(result["status"], "restored")
        self.assertIn("release/local:release/local", push.call_args.args[0])

    def test_merge_uses_exact_head_precondition(self) -> None:
        args = argparse.Namespace(
            repo_root=pathlib.Path.cwd(),
            repo="owner/repo",
            pr="17",
            merge_method="merge",
            admin=False,
            auto=False,
            delete_branch=False,
        )
        response = {
            "number": 17,
            "url": "https://example.test/pr/17",
            "state": "MERGED",
            "headRefOid": self.commit,
            "mergedAt": "2026-07-25T00:00:00Z",
            "mergeCommit": {"oid": "b" * 40},
        }
        with (
            mock.patch.object(merge, "require_success") as run_merge,
            mock.patch.object(
                merge, "require_output", return_value=json.dumps(response)
            ),
        ):
            result = merge.merge_verified_pr(args, expected_head=self.commit)

        command = run_merge.call_args.args[0]
        self.assertEqual(
            command[command.index("--match-head-commit") + 1], self.commit
        )
        self.assertEqual(result["status"], "merged")


class DependencyFinalizationTests(unittest.TestCase):
    def test_dependency_merge_passes_the_preflight_approved_head(self) -> None:
        approved_head = "a" * 40
        completed = argparse.Namespace(
            returncode=0,
            stdout='{"status":"merged"}',
            stderr="",
        )
        with mock.patch.object(
            dependency_finalization,
            "run_command",
            return_value=completed,
        ) as run:
            result, error = dependency_finalization.merge_pr(
                "owner/repo",
                17,
                pathlib.Path.cwd(),
                "merge",
                expected_head=approved_head,
                admin=False,
                wait_seconds=0,
                interval_seconds=1,
            )

        command = run.call_args.args[0]
        self.assertEqual(
            command[command.index("--expected-head") + 1],
            approved_head,
        )
        self.assertEqual(result, {"status": "merged"})
        self.assertIsNone(error)

    def test_dependency_head_binding_requires_new_preflight(self) -> None:
        approved_head = "a" * 40
        live = {"head_oid": "b" * 40}

        blocker = dependency_finalization.head_binding_blocker(
            "owner/repo",
            17,
            approved_head,
            live,
        )

        self.assertEqual(blocker["check"], "preflight_head")
        self.assertIn("run a new preflight and approval", blocker["message"])

    def test_merge_rejects_a_head_other_than_the_external_approval(self) -> None:
        args = argparse.Namespace(
            repo_root=pathlib.Path.cwd(),
            repo="owner/repo",
            pr="17",
            merge_method="merge",
            expected_head="a" * 40,
            admin=False,
            auto=False,
            delete_branch=False,
            wait_seconds=0,
            interval_seconds=1,
        )
        with mock.patch.object(
            merge,
            "_validate_readiness",
            return_value={"head_oid": "b" * 40},
        ):
            with self.assertRaisesRegex(
                merge.WorkflowError,
                "externally approved commit",
            ):
                merge.merge_pr(args)


if __name__ == "__main__":
    unittest.main()
