import json
import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER = (
    ROOT
    / "skills"
    / "ceratops-skill-lifecycle"
    / "scripts"
    / "push-release-branch-and-ensure-pr.ps1"
)


class PushReleaseBranchHelperTests(unittest.TestCase):
    shell: str
    function_source: str

    @classmethod
    def setUpClass(cls):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell is None:
            raise unittest.SkipTest("PowerShell is unavailable")
        cls.shell = shell
        source = HELPER.read_text(encoding="utf-8")
        marker = "$currentBranch ="
        if marker not in source:
            raise AssertionError("helper function boundary was not found")
        cls.function_source = source.split(marker, 1)[0]

    def run_function_test(self, body: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self.shell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                self.function_source + body,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_waits_until_github_reports_the_pushed_head(self):
        process = self.run_function_test(
            r"""
$script:calls = 0
function Get-OpenPrForBranch {
    $script:calls += 1
    $head = if ($script:calls -lt 3) { "old" } else { "new" }
    return [pscustomobject]@{ headRefOid = $head }
}
$pr = Wait-OpenPrAtHead -ExpectedHead "new" -MaxAttempts 4 -DelaySeconds 0
[pscustomobject]@{ head = $pr.headRefOid; calls = $script:calls } |
    ConvertTo-Json -Compress
"""
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(
            json.loads(process.stdout.strip()), {"head": "new", "calls": 3}
        )

    def test_stops_after_the_bounded_attempt_count(self):
        process = self.run_function_test(
            r"""
$script:calls = 0
function Get-OpenPrForBranch {
    $script:calls += 1
    return [pscustomobject]@{ headRefOid = "old" }
}
try {
    Wait-OpenPrAtHead -ExpectedHead "new" -MaxAttempts 3 -DelaySeconds 0 | Out-Null
    throw "Expected Wait-OpenPrAtHead to fail."
} catch {
    [pscustomobject]@{ message = $_.Exception.Message; calls = $script:calls } |
        ConvertTo-Json -Compress
}
"""
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout.strip())
        self.assertEqual(result["calls"], 3)
        self.assertIn("after 3 attempts", result["message"])


if __name__ == "__main__":
    unittest.main()
