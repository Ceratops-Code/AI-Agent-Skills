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

from github_pr_workflow import ensure_pr, merge, ship  # noqa: E402


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
                allow_admin_review_bypass=False,
            )

        self.assertEqual(result["pending"], 0)
        validate.assert_called_once()

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
            return {"head_oid": self.commit}

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

    def test_ship_removes_only_its_successful_checkpoint(self) -> None:
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
            unrelated_checkpoint = repo_root / "unrelated.json"
            unrelated_checkpoint.write_text("unrelated", encoding="utf-8")
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
                mock.patch.object(ship, "run_parallel_gates") as gates,
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
            unrelated_retained = unrelated_checkpoint.exists()

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
        self.assertTrue(unrelated_retained)
        ensure.assert_called_once()
        self.assertEqual(gates.call_count, 2)
        merge_pr.assert_called_once()
        self.assertEqual(merge_pr.call_args.args[0].wait_seconds, 0)
        sync_main.assert_called_once()

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


if __name__ == "__main__":
    unittest.main()
