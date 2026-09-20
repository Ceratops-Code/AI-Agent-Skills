"""Behavior checks for Dependabot manifest classification and coverage."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "ceratops-repo-lifecycle" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from github_contract_engine.collectors.local_repository import (  # noqa: E402
    collect_local_repository,
)


class DependabotCoverageTests(unittest.TestCase):
    def test_dependabot_ecosystems_distinguish_uv_and_pip_manifests(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "demo"\n',
                encoding="utf-8",
            )

            pip_only = collect_local_repository(temporary_directory, [])
            self.assertEqual(
                pip_only["dependabot"]["ecosystems"],
                {"pip": ["pyproject.toml"]},
            )

            (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
            uv_only = collect_local_repository(temporary_directory, [])
            self.assertEqual(
                uv_only["dependabot"]["ecosystems"],
                {"uv": ["pyproject.toml", "uv.lock"]},
            )

            (root / "requirements-dev.txt").write_text(
                "pytest\n",
                encoding="utf-8",
            )
            mixed = collect_local_repository(temporary_directory, [])
            self.assertEqual(
                mixed["dependabot"]["ecosystems"],
                {
                    "pip": ["requirements-dev.txt"],
                    "uv": ["pyproject.toml", "uv.lock"],
                },
            )

