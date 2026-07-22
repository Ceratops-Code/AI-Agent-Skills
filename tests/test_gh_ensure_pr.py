from __future__ import annotations

import argparse
import pathlib
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
GH_SCRIPTS = ROOT / "skills" / "ceratops-gh-repo-lifecycle" / "scripts"
sys.path.insert(0, str(GH_SCRIPTS))

from github_pr_workflow import ensure_pr  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
