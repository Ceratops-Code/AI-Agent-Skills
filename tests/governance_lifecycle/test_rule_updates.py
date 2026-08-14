from __future__ import annotations

import hashlib
import json
import pathlib

from tests.governance_lifecycle.support import (
    run_rule_candidate_validator,
    target_repository_markdown_policy,
    write_rule_candidate,
)


def test_rule_candidate_repairs_multiple_targets_and_is_idempotent(
    tmp_path: pathlib.Path,
) -> None:
    first_repo = tmp_path / "first-repo"
    second_repo = tmp_path / "second-repo"
    first_repo.mkdir()
    second_repo.mkdir()
    first = first_repo / "contract.md"
    second = second_repo / "contract.md"
    first_text = (
        "# First\n\n"
        "Old prose.\n\n"
        "- Old nested item.\n\n"
        "> > - Old quoted item.\n\n"
        "````text\n"
        "```\n"
        "protected code line that is intentionally much longer than the limit\n"
        "````\n\n"
        "A [sample link][sample].\n\n"
        "[sample]: https://example.test/reference\n"
        "  \"Old reference title.\"\n"
    )
    second_text = "# Second\n\nOld alpha.\n\nOld beta.\n"
    first.write_text(first_text, encoding="utf-8", newline="\n")
    second.write_text(second_text, encoding="utf-8", newline="\r\n")
    candidate = tmp_path / "candidate.json"
    evidence = tmp_path / "evidence.json"
    first_replacements = [
        {
            "expected_old": "Old prose.",
            "replacement": (
                "Safe ordinary prose wraps deterministically while preserving "
                "every original non-whitespace content character."
            ),
        },
        {
            "expected_old": "- Old nested item.",
            "replacement": (
                "- Nested list continuation wrapping preserves its exact "
                "nesting and marker structure."
            ),
        },
        {
            "expected_old": "> > - Old quoted item.",
            "replacement": (
                "> > - Nested blockquote continuation wrapping preserves "
                "both quote depths and list nesting."
            ),
        },
        {
            "expected_old": (
                "````text\n"
                "```\n"
                "protected code line that is intentionally much longer than the limit\n"
                "````"
            ),
            "replacement": (
                "````text\n"
                "```\n"
                "protected code line that is intentionally much longer than the limit\n"
                "````"
            ),
        },
        {
            "expected_old": '  "Old reference title."',
            "replacement": (
                '  "A reference definition continuation remains byte-for-byte '
                'unwrapped under its surrounding Markdown context."'
            ),
        },
    ]
    second_replacements = [
        {
            "expected_old": "Old alpha.",
            "replacement": "Alpha stays on one line under its wider configured policy.",
        },
        {
            "expected_old": "Old beta.",
            "replacement": (
                "Beta remains independently replaceable and wraps with the "
                "second target's CRLF convention when it exceeds that policy."
            ),
        },
    ]
    write_rule_candidate(
        candidate,
        rule_stack=[first, second],
        targets=[
            {
                "rules": str(first.resolve()),
                "history": None,
                "source_sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
                "markdown_policy": None,
                "replacements": first_replacements,
            },
            {
                "rules": str(second.resolve()),
                "history": None,
                "source_sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
                "markdown_policy": None,
                "replacements": second_replacements,
            },
        ],
    )
    original_sources = (first.read_bytes(), second.read_bytes())
    validated = run_rule_candidate_validator(candidate, evidence)
    assert validated.returncode == 0, validated.stderr
    assert validated.stdout.strip() == "OK"
    fixed = json.loads(candidate.read_text(encoding="utf-8"))
    fixed_first = fixed["targets"][0]["replacements"]
    fixed_second = fixed["targets"][1]["replacements"]
    assert "\n" in fixed_first[0]["replacement"]
    assert "\n  " in fixed_first[1]["replacement"]
    assert "\n> >   " in fixed_first[2]["replacement"]
    assert fixed_first[3]["replacement"] == first_replacements[3]["replacement"]
    assert fixed_first[4]["replacement"] == first_replacements[4]["replacement"]
    assert "\n" not in fixed_second[0]["replacement"]
    assert "\r\n" in fixed_second[1]["replacement"]
    assert "\n" not in fixed_second[1]["replacement"].replace("\r\n", "")
    assert (first.read_bytes(), second.read_bytes()) == original_sources
    detail = json.loads(evidence.read_text(encoding="utf-8"))
    assert detail["status"] == "passed" and detail["idempotent"] is True
    first_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    second_evidence = tmp_path / "second-evidence.json"
    repeated = run_rule_candidate_validator(candidate, second_evidence)
    assert repeated.returncode == 0, repeated.stderr
    assert hashlib.sha256(candidate.read_bytes()).hexdigest() == first_hash
    assert json.loads(second_evidence.read_text(encoding="utf-8"))["changed"] is False


def test_rule_candidate_failures_are_atomic_and_actionable(
    tmp_path: pathlib.Path,
) -> None:
    safe_repo = tmp_path / "safe-repo"
    blocked_repo = tmp_path / "blocked-repo"
    safe_repo.mkdir()
    blocked_repo.mkdir()
    safe = safe_repo / "contract.md"
    blocked = blocked_repo / "contract.md"
    safe.write_text("Old safe.\n", encoding="utf-8", newline="\n")
    blocked.write_text("Old blocked.\n", encoding="utf-8", newline="\n")
    candidate = tmp_path / "atomic-candidate.json"
    evidence = tmp_path / "atomic-evidence.json"
    token = "https://example.test/" + "x" * 70
    write_rule_candidate(
        candidate,
        rule_stack=[safe, blocked],
        targets=[
            {
                "rules": str(safe.resolve()),
                "history": None,
                "source_sha256": hashlib.sha256(safe.read_bytes()).hexdigest(),
                "markdown_policy": None,
                "replacements": [
                    {
                        "expected_old": "Old safe.",
                        "replacement": (
                            "Safe prose would wrap if every target completed "
                            "mechanical validation."
                        ),
                    }
                ],
            },
            {
                "rules": str(blocked.resolve()),
                "history": None,
                "source_sha256": hashlib.sha256(blocked.read_bytes()).hexdigest(),
                "markdown_policy": None,
                "replacements": [
                    {"expected_old": "Old blocked.", "replacement": token}
                ],
            },
        ],
    )
    before = candidate.read_bytes()
    failed = run_rule_candidate_validator(candidate, evidence)
    assert failed.returncode == 1
    assert str(blocked.resolve()) in failed.stderr
    assert "replacement=0" in failed.stderr
    assert "configured limit 80" in failed.stderr
    assert "indivisible token" in failed.stderr
    assert candidate.read_bytes() == before
    assert json.loads(evidence.read_text(encoding="utf-8"))["status"] == "failed"

    target_policy = target_repository_markdown_policy(safe_repo)
    write_rule_candidate(
        candidate,
        rule_stack=[safe],
        targets=[
            {
                "rules": str(safe.resolve()),
                "history": None,
                "source_sha256": hashlib.sha256(safe.read_bytes()).hexdigest(),
                "markdown_policy": target_policy,
                "replacements": [
                    {"expected_old": "Old safe.", "replacement": "safe value"}
                ],
            }
        ],
    )
    before_mutation = candidate.read_bytes()
    mutated = run_rule_candidate_validator(candidate, tmp_path / "mutation.json")
    assert mutated.returncode == 1
    assert "skill-owned policy" in mutated.stderr
    assert candidate.read_bytes() == before_mutation


def test_rule_candidate_rejects_stale_and_duplicate_expected_old(
    tmp_path: pathlib.Path,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    target = repository / "contract.md"
    target.write_text("Old value.\n", encoding="utf-8", newline="\n")
    candidate = tmp_path / "candidate.json"
    target_entry: dict[str, object] = {
        "rules": str(target.resolve()),
        "history": None,
        "source_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "markdown_policy": None,
        "replacements": [
            {"expected_old": "Old value.", "replacement": "New value."},
            {"expected_old": "Old value.", "replacement": "Other value."},
        ],
    }
    write_rule_candidate(
        candidate,
        rule_stack=[target],
        targets=[target_entry],
    )
    duplicate = run_rule_candidate_validator(candidate, tmp_path / "duplicate.json")
    assert duplicate.returncode == 1
    assert "duplicates expected_old" in duplicate.stderr

    target_entry["replacements"] = [
        {"expected_old": "Old value.", "replacement": "New value."}
    ]
    write_rule_candidate(candidate, rule_stack=[target], targets=[target_entry])
    target.write_text("Changed value.\n", encoding="utf-8", newline="\n")
    stale = run_rule_candidate_validator(candidate, tmp_path / "stale.json")
    assert stale.returncode == 1
    assert "source-hash" in stale.stderr and "source is stale" in stale.stderr
