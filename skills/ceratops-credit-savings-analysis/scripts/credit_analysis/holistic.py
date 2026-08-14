"""Shared causal-episode planning and Luna/Sol orchestration."""
# ruff: noqa: F401,F403,F405,I001

from __future__ import annotations

from .batch import *
from .core import *

def _exclusive_text(path: pathlib.Path, value: str, label: str) -> None:
    """Create one immutable UTF-8 controller artifact."""

    if path.exists() or path.is_symlink():
        raise CreditAnalysisError(f"refusing to overwrite {label}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
    except OSError as exc:
        raise CreditAnalysisError(f"could not write {label}: {exc}") from exc


def _codex_model_catalog() -> dict[str, dict[str, Any]]:
    """Read local model, effort, and context limits without a model request."""

    executable = shutil.which("codex")
    if executable is None:
        raise CreditAnalysisError("Codex CLI is unavailable")
    try:
        completed = subprocess.run(
            [executable, "debug", "models"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CreditAnalysisError(f"could not read the Codex model catalog: {exc}") from exc
    if completed.returncode:
        detail = " ".join((completed.stderr or completed.stdout).split())
        raise CreditAnalysisError(
            "could not read the Codex model catalog"
            + (f": {detail[:500]}" if detail else "")
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CreditAnalysisError("Codex model catalog is invalid JSON") from exc
    models = payload.get("models") if isinstance(payload, Mapping) else None
    if not isinstance(models, list):
        raise CreditAnalysisError("Codex model catalog has no model list")
    catalog: dict[str, dict[str, Any]] = {}
    for item in models:
        if not isinstance(item, Mapping) or not isinstance(item.get("slug"), str):
            continue
        levels = item.get("supported_reasoning_levels")
        efforts = (
            {
                str(level["effort"])
                for level in levels
                if isinstance(level, Mapping)
                and isinstance(level.get("effort"), str)
            }
            if isinstance(levels, list)
            else set()
        )
        context = item.get("context_window")
        percent = item.get("effective_context_window_percent")
        effective_context_tokens = None
        if (
            isinstance(context, int)
            and not isinstance(context, bool)
            and context > 0
            and isinstance(percent, (int, float))
            and not isinstance(percent, bool)
            and 0 < percent <= 100
        ):
            effective_context_tokens = math.floor(context * percent / 100)
        catalog[str(item["slug"])] = {
            "reasoning_efforts": efforts,
            "effective_context_tokens": effective_context_tokens,
        }
    if not catalog:
        raise CreditAnalysisError("Codex model catalog is empty")
    return catalog






def _surface_order_for_request(
    request: Mapping[str, Any], contract: Mapping[str, Any]
) -> list[str]:
    if request["mode"] == "full-analysis":
        return list(contract["surface_order"])
    return [str(request["action"])]


def _review_record_index(evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    model_review = evidence.get("model_review")
    if not isinstance(model_review, Mapping):
        raise CreditAnalysisError("model-review evidence is invalid")
    records = model_review.get("records")
    if not isinstance(records, list):
        raise CreditAnalysisError("model-review records are invalid")
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise CreditAnalysisError("model-review record is invalid")
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or record_id in indexed:
            raise CreditAnalysisError("model-review record ID is invalid")
        indexed[record_id] = record
    return indexed


def _run_index(evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    runs = evidence.get("runs")
    if not isinstance(runs, list):
        raise CreditAnalysisError("evidence runs are invalid")
    result: dict[str, dict[str, Any]] = {}
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("turn_id"), str):
            raise CreditAnalysisError("evidence run is invalid")
        if run["turn_id"] in result:
            raise CreditAnalysisError("duplicate evidence run")
        result[run["turn_id"]] = run
    return result


SURFACE_EVIDENCE_KEYWORDS = {
    "helper-contracts": (
        "helper",
        "script",
        "contract",
        "cleanup",
        "rollback",
        "dependency",
        "output",
    ),
    "context-evidence": (
        "read",
        "search",
        "context",
        "evidence",
        "token",
        "cached",
        "path",
    ),
    "rework-validation": (
        "failed",
        "error",
        "retry",
        "again",
        "temporary",
        "workaround",
        "patch",
        "revert",
        "correct",
    ),
    "tool-flow": (
        "tool",
        "command",
        "wait",
        "timeout",
        "terminated",
        "result",
        "exit",
    ),
    "instruction-reasoning": (
        "instruction",
        "rule",
        "prompt",
        "clarif",
        "approve",
        "plan",
        "skill",
    ),
}
OUTCOME_KEYS = frozenset(
    {
        "code",
        "error",
        "errors",
        "exit_code",
        "returncode",
        "status",
        "stderr",
        "success",
        "terminated",
        "termination",
        "timed_out",
        "timeout",
    }
)


def _structured_outcome(value: Any, *, depth: int = 0) -> Any:
    """Project explicit process/result telemetry without semantic judgment."""

    if depth > 5:
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in OUTCOME_KEYS:
                result[str(key)] = _bounded_value(item, text_limit=600)
                continue
            nested = _structured_outcome(item, depth=depth + 1)
            if nested not in (None, {}, []):
                result[str(key)] = nested
        return result or None
    if isinstance(value, list):
        items = [
            projected
            for item in value
            if (projected := _structured_outcome(item, depth=depth + 1))
            is not None
        ]
        return items or None
    return None


def _relevant_segments(text: str, surface_id: str) -> list[dict[str, Any]]:
    """Retain bounded deterministic windows around surface-relevant terms."""

    lowered = text.casefold()
    segments: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for keyword in SURFACE_EVIDENCE_KEYWORDS[surface_id]:
        start = 0
        while len(segments) < 4:
            position = lowered.find(keyword, start)
            if position < 0:
                break
            left = max(0, position - 350)
            right = min(len(text), position + len(keyword) + 650)
            bounds = (left, right)
            if not any(left < old_right and right > old_left for old_left, old_right in seen):
                seen.add(bounds)
                segments.append(
                    {
                        "start": left,
                        "end": right,
                        "text": text[left:right],
                    }
                )
            start = position + len(keyword)
        if len(segments) >= 4:
            break
    return segments


def _shared_relevant_segments(
    text: str,
    surface_ids: Sequence[str],
    *,
    text_limit: int,
) -> list[dict[str, Any]]:
    """Keep one deterministic non-overlapping segment per applicable surface."""

    result: list[dict[str, Any]] = []
    bounds: list[tuple[int, int]] = []
    for surface_id in surface_ids:
        for segment in _relevant_segments(text, surface_id):
            start = int(segment["start"])
            end = int(segment["end"])
            if any(start < prior_end and end > prior_start for prior_start, prior_end in bounds):
                continue
            bounds.append((start, end))
            result.append(
                {
                    "surface_id": surface_id,
                    "start": start,
                    "end": end,
                    "text": str(segment["text"])[:text_limit],
                }
            )
            break
    return result


CANONICAL_REFERENCE_RE = re.compile(
    r"(?:<workspace:[^>]+>|<codex-home>|\$CODEX_HOME)"
    r"(?:[\\/][^\s\"'<>|,;}\]]+)*"
)
WORKSPACE_LOCATION_RE = re.compile(
    r"(?P<separator>[:-])(?P<line>[1-9]\d*)(?P<terminator>[:-])"
)


def _analysis_policy(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the closed full-analysis policy embedded in every child packet."""

    policy = contract.get("analysis_policy")
    expected = {
        "implementation_status_source": "frozen-current-canonical-state",
        "existing_control_classification": (
            "implemented-compliance-or-runtime-gap"
        ),
        "excluded_waste": ["intentional-full-skill-body-injection"],
        "prohibited_recommendations": ["reasoning-settings-or-levels"],
        "external_research": "targeted-official-sources-only",
        "broader_research_handoff": "paste-ready-prompt",
        "mutation_authority": False,
        "outstanding_finding_cap": None,
    }
    if policy != expected:
        raise CreditAnalysisError("analysis policy contract is invalid")
    return dict(policy)


def _canonical_artifact_references(text: str) -> list[str]:
    refs: list[str] = []
    for match in CANONICAL_REFERENCE_RE.finditer(text):
        value = match.group(0).replace("\\", "/").rstrip(".")
        if value.startswith("$CODEX_HOME"):
            value = "<codex-home>" + value[len("$CODEX_HOME") :]
        root_label, separator, relative = value.partition(">")
        if separator:
            value = root_label + separator + re.sub(r"/+", "/", relative)
        if value not in refs:
            refs.append(value)
    return refs


def _canonical_workspace_target(
    reference: str,
    canonical_roots: Mapping[str, pathlib.Path],
) -> tuple[str, pathlib.Path | None, dict[str, Any] | None, str | None]:
    """Resolve one protected root reference without treating line output as a filename.

    Exact files win. Otherwise the longest existing prefix immediately before an
    ``rg``-style line marker becomes the canonical artifact, while the location
    remains separate metadata. The caller still enforces workspace and symlink
    boundaries before reading the target.
    """

    match = re.fullmatch(
        r"(<workspace:[^>]+>|<codex-home>)(?:/(.*))?", reference
    )
    if match is None or match.group(1) not in canonical_roots:
        return reference, None, None, "canonical-root-unavailable"
    root_label = match.group(1)
    canonical_root = canonical_roots[root_label]
    relative = match.group(2) or ""
    parts = [part for part in re.split(r"[\\/]+", relative) if part]
    if any(part in {".", ".."} for part in parts):
        return reference, None, None, "unsafe-relative-reference"
    exact = canonical_root.joinpath(*parts)
    if exact.exists():
        return reference, exact, None, None

    candidates: list[tuple[int, pathlib.Path, str, re.Match[str]]] = []
    for location_match in WORKSPACE_LOCATION_RE.finditer(relative):
        candidate_relative = relative[: location_match.start()].rstrip("/\\")
        candidate_parts = [
            part for part in re.split(r"[\\/]+", candidate_relative) if part
        ]
        if not candidate_parts or any(
            part in {".", ".."} for part in candidate_parts
        ):
            continue
        candidate = canonical_root.joinpath(*candidate_parts)
        if candidate.exists():
            candidates.append(
                (
                    len(candidate_relative),
                    candidate,
                    candidate_relative,
                    location_match,
                )
            )
    if not candidates:
        return reference, exact, None, None

    _, target, canonical_relative, location_match = max(
        candidates, key=lambda item: item[0]
    )
    suffix = relative[location_match.end() :]
    normalized_relative = canonical_relative.replace("\\", "/")
    canonical_reference = f"{root_label}/{normalized_relative}"
    separator = location_match.group("separator")
    location = {
        "line": int(location_match.group("line")),
        "relation": "match" if separator == ":" else "context",
        "syntax": f"{separator}line{location_match.group('terminator')}",
        "source_reference_sha256": hashlib.sha256(
            reference.encode("utf-8")
        ).hexdigest(),
        "trailing_chars": len(suffix),
        "trailing_sha256": hashlib.sha256(suffix.encode("utf-8")).hexdigest(),
    }
    return canonical_reference, target, location, None


def _canonical_references_from_evidence(evidence: Mapping[str, Any]) -> list[str]:
    """Inventory portable current-source references without exposing local roots."""

    references: list[str] = []
    model_review = evidence.get("model_review")
    records = model_review.get("records") if isinstance(model_review, Mapping) else None
    if not isinstance(records, list):
        raise CreditAnalysisError("model-review records are unavailable")
    for record in records:
        if not isinstance(record, Mapping):
            raise CreditAnalysisError("model-review record is invalid")
        serialized = json.dumps(
            record.get("content"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        for reference in _canonical_artifact_references(serialized):
            if reference not in references:
                references.append(reference)
    if "<codex-home>/AGENTS.md" not in references:
        references.append("<codex-home>/AGENTS.md")
    complete_serialized = json.dumps(
        evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    automation_ids = []
    for suffix in complete_serialized.split("Automation ID:")[1:]:
        match = re.match(r"\s*(?P<id>[A-Za-z0-9_.-]+)", suffix)
        if match is None or match.group("id") in automation_ids:
            continue
        automation_ids.append(match.group("id"))
    for automation_id in automation_ids:
        automation_reference = (
            f"<codex-home>/automations/{automation_id}/automation.toml"
        )
        if automation_reference not in references:
            references.append(automation_reference)
    return references


def _canonical_projection(text: str) -> dict[str, Any]:
    """Project protected final-state text while retaining its complete snapshot."""

    segments: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for surface_id in SURFACE_EVIDENCE_KEYWORDS:
        for segment in _relevant_segments(text, surface_id):
            bounds = (int(segment["start"]), int(segment["end"]))
            if bounds not in seen:
                seen.add(bounds)
                segments.append(segment)
            if len(segments) >= 8:
                break
        if len(segments) >= 8:
            break
    return {
        "protected_chars": len(text),
        "protected_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "head": text[:1400],
        "tail": text[-1400:],
        "relevant_segments": segments,
    }


def _collect_canonical_state_snapshot(
    *,
    evidence: Mapping[str, Any],
    path_roots: list[tuple[str, str]],
    orchestration_root: pathlib.Path,
    ledger: ModuleType,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Read referenced final artifacts once and retain protected immutable evidence."""

    snapshot_root = orchestration_root / "canonical-state"
    payload_root = snapshot_root / "payloads"
    snapshot_root.mkdir(parents=True, exist_ok=False)
    payload_root.mkdir()
    canonical_roots = {
        label: pathlib.Path(root).expanduser().resolve()
        for root, label in path_roots
        if label == "<codex-home>" or label.startswith("<workspace:")
    }
    grouped: list[dict[str, Any]] = []
    grouped_by_target: dict[str, dict[str, Any]] = {}
    for reference in _canonical_references_from_evidence(evidence):
        canonical_reference, unresolved, location, initial_status = (
            _canonical_workspace_target(reference, canonical_roots)
        )
        if unresolved is None:
            target_key = f"reference:{canonical_reference}"
        else:
            target_key = "path:" + os.path.normcase(
                str(unresolved.resolve(strict=False))
            )
        group = grouped_by_target.get(target_key)
        if group is None:
            group = {
                "artifact_reference": canonical_reference,
                "unresolved": unresolved,
                "initial_status": initial_status,
                "observed_references": [],
                "locations": [],
            }
            grouped_by_target[target_key] = group
            grouped.append(group)
        observed = group["observed_references"]
        if reference not in observed:
            observed.append(reference)
        locations = group["locations"]
        if location is not None and location not in locations:
            locations.append(location)

    retained_records: list[dict[str, Any]] = []
    public_by_reference: dict[str, dict[str, Any]] = {}
    for ordinal, group in enumerate(grouped, start=1):
        reference = str(group["artifact_reference"])
        unresolved = group["unresolved"]
        initial_status = group["initial_status"]
        artifact_id = f"canonical.{ordinal:04d}"
        public: dict[str, Any] = {
            "id": artifact_id,
            "artifact_reference": reference,
            "source_reference_count": len(group["observed_references"]),
            "observed_references": list(group["observed_references"]),
            "locations": list(group["locations"]),
            "evidence_ref": f"evidence://canonical-state/{artifact_id}",
            "status": "unresolved",
            "kind": None,
            "source_bytes": None,
            "source_sha256": None,
            "retained_snapshot": None,
            "projection": None,
        }
        snapshot_path: pathlib.Path | None = None
        if initial_status is not None:
            public["status"] = initial_status
        elif not isinstance(unresolved, pathlib.Path):
            public["status"] = "workspace-root-unavailable"
        else:
            root_match = re.match(
                r"(<workspace:[^>]+>|<codex-home>)", reference
            )
            if root_match is None or root_match.group(1) not in canonical_roots:
                public["status"] = "canonical-root-unavailable"
            else:
                canonical_root = canonical_roots[root_match.group(1)]
                resolved = unresolved.resolve(strict=False)
                if not (
                    resolved == canonical_root
                    or resolved.is_relative_to(canonical_root)
                ):
                    public["status"] = "outside-canonical-root"
                elif unresolved.is_symlink():
                    public["status"] = "symlink-withheld"
                elif not unresolved.exists():
                    public["status"] = "missing"
                elif unresolved.is_dir():
                    try:
                        listing = "\n".join(
                            sorted(child.name for child in unresolved.iterdir())
                        )
                    except OSError:
                        public.update(
                            {"status": "read-error", "kind": "directory-listing"}
                        )
                    else:
                        protected = ledger.prepare_review_text(listing, path_roots)
                        snapshot_path = payload_root / f"{artifact_id}.txt"
                        _exclusive_text(
                            snapshot_path,
                            protected,
                            "canonical directory snapshot",
                        )
                        public.update(
                            {
                                "status": "captured",
                                "kind": "directory-listing",
                                "source_bytes": len(listing.encode("utf-8")),
                                "source_sha256": hashlib.sha256(
                                    listing.encode("utf-8")
                                ).hexdigest(),
                                "projection": _canonical_projection(protected),
                            }
                        )
                elif unresolved.is_file():
                    try:
                        data = unresolved.read_bytes()
                    except OSError:
                        public.update({"status": "read-error", "kind": "file"})
                    else:
                        public["source_bytes"] = len(data)
                        public["source_sha256"] = hashlib.sha256(data).hexdigest()
                        try:
                            decoded = data.decode("utf-8")
                        except UnicodeDecodeError:
                            public.update(
                                {"status": "captured", "kind": "binary-hash"}
                            )
                        else:
                            protected = ledger.prepare_review_text(decoded, path_roots)
                            snapshot_path = payload_root / f"{artifact_id}.txt"
                            _exclusive_text(
                                snapshot_path,
                                protected,
                                "canonical file snapshot",
                            )
                            public.update(
                                {
                                    "status": "captured",
                                    "kind": "protected-text",
                                    "projection": _canonical_projection(protected),
                                }
                            )
                else:
                    public["status"] = "unsupported-artifact-kind"
        retained = dict(public)
        if snapshot_path is not None:
            snapshot_hash = _file_hash(snapshot_path)
            retained["snapshot_path"] = str(snapshot_path)
            retained["snapshot_sha256"] = snapshot_hash
            public["retained_snapshot"] = {
                "complete": True,
                "sha256": snapshot_hash,
                "evidence_ref": public["evidence_ref"],
            }
        else:
            retained["snapshot_path"] = None
            retained["snapshot_sha256"] = None
        retained_records.append(retained)
        public_by_reference[reference] = public
    index = {
        "schema": CANONICAL_STATE_SCHEMA,
        "record_count": len(retained_records),
        "records": retained_records,
    }
    index_path = snapshot_root / "index.json"
    _exclusive_json(index_path, index, "canonical-state index")
    return public_by_reference, {
        "path": str(index_path),
        "sha256": _file_hash(index_path),
        "record_count": len(retained_records),
    }










def _has_failure_telemetry(value: Any) -> bool:
    """Detect only explicit observable failure, timeout, or termination fields."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in {"exit_code", "returncode", "code"}:
                if isinstance(item, int) and not isinstance(item, bool) and item != 0:
                    return True
            elif normalized in {"timed_out", "timeout", "terminated", "termination"}:
                if item is True or (
                    isinstance(item, str)
                    and item.casefold() in {"true", "timeout", "terminated", "killed"}
                ):
                    return True
            elif normalized in {"explicit_failure", "semantic_failure"} and item is True:
                return True
            elif normalized in {"error", "errors", "stderr"} and (
                item is not None and item != "" and item != [] and item != {}
            ):
                return True
            elif normalized == "status" and isinstance(item, str) and item.casefold() in {
                "error",
                "failed",
                "failure",
                "timeout",
                "terminated",
            }:
                return True
            if _has_failure_telemetry(item):
                return True
    elif isinstance(value, list):
        return any(_has_failure_telemetry(item) for item in value)
    return False


def _observable_high_signal_reasons(
    *,
    call: Mapping[str, Any],
    messages: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    repeated_groups: Sequence[Mapping[str, Any]],
    volume: Mapping[str, Any],
) -> list[str]:
    """Route observable review signals without classifying waste or necessity."""

    reasons: list[str] = []
    telemetry = [
        call.get("tool_results"),
        *[record.get("structured_outcome") for record in records],
    ]
    if any(_has_failure_telemetry(item) for item in telemetry):
        reasons.append("failure-timeout-or-termination-telemetry")
    if repeated_groups:
        reasons.append("repeated-action-fingerprint")
    searchable = json.dumps(
        {
            "actions": call.get("actions"),
            "semantic_actions": call.get("semantic_actions"),
            "messages": messages,
            "records": records,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    ).casefold()
    if re.search(
        r"\b(correct(?:ion|ed)?|revert(?:ed|ing)?|retry|workaround|temporary|"
        r"rolled back|undo|again)\b",
        searchable,
    ):
        reasons.append("correction-retry-or-temporary-control")
    tokens = volume.get("tokens")
    input_tokens = tokens.get("input_tokens") if isinstance(tokens, Mapping) else None
    output_tokens = tokens.get("output_tokens") if isinstance(tokens, Mapping) else None
    if (
        (isinstance(input_tokens, int) and input_tokens >= 100_000)
        or (isinstance(output_tokens, int) and output_tokens >= 25_000)
        or int(volume.get("tool_result_chars") or 0) >= 100_000
    ):
        reasons.append("large-input-output-volume")
    return reasons
























def _task_artifact_paths(root: pathlib.Path, task_id: str) -> dict[str, str]:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id)
    return {
        "input": str(root / "inputs" / f"{safe}.json"),
        "prompt": str(root / "prompts" / f"{safe}.md"),
        "schema": str(root / "schemas" / f"{safe}.json"),
        "aliases": str(root / "schemas" / f"{safe}.aliases.json"),
        "result": str(root / "results" / f"{safe}.json"),
        "attempts": str(root / "attempts" / safe),
    }
































LUNA_ASSESSMENT_FIELDS = {
    "candidate_ids",
    "surface_id",
    "disposition",
    "reason",
    "evidence_refs",
}
LUNA_FINDING_FIELDS = {
    "id",
    "title",
    "problem_summary",
    "candidate_ids",
    "surface_id",
    "evidence_refs",
    "producer_type",
    "producer_owner",
    "proposed_durable_control",
    "recurrence_likely",
    "savings_justifies_maintenance",
    "material_variant_ids",
}
LUNA_RISK_FIELDS = {
    "id",
    "description",
    "candidate_ids",
    "surface_id",
    "evidence_refs",
    "verification_needed",
    "material_variant_ids",
}
LUNA_TEMPORARY_FIELDS = {
    "id",
    "problem_solved",
    "candidate_ids",
    "surface_id",
    "observed_temporary_control",
    "canonical_owner_hint",
    "evidence_refs",
    "material_variant_ids",
}
LUNA_CHILD_ASSESSMENT_FIELDS = (LUNA_ASSESSMENT_FIELDS - {"surface_id"}) | {
    "provisional_findings",
    "plausible_risks",
    "temporary_control_candidates",
}
LUNA_PRIMARY_CHILD_ASSESSMENT_FIELDS = (
    LUNA_CHILD_ASSESSMENT_FIELDS - {"candidate_ids"}
) | {"candidate_id", "surface_id"}
LUNA_SHARED_CONSOLIDATION_CHILD_ASSESSMENT_FIELDS = (
    LUNA_CHILD_ASSESSMENT_FIELDS | {"surface_id"}
)
LUNA_CHILD_FINDING_FIELDS = LUNA_FINDING_FIELDS - {"candidate_ids", "surface_id"}
LUNA_CHILD_RISK_FIELDS = LUNA_RISK_FIELDS - {"candidate_ids", "surface_id"}
LUNA_CHILD_TEMPORARY_FIELDS = LUNA_TEMPORARY_FIELDS - {
    "candidate_ids",
    "surface_id",
}
LUNA_CHILD_RESULT_FIELDS = {
    "schema",
    "analysis_id",
    "task_id",
    "surface_id",
    "stage",
    "input_sha256",
    "candidate_assessments",
    "preserved_variant_ids",
}
LUNA_RESULT_FIELDS = {
    "schema",
    "analysis_id",
    "task_id",
    "surface_id",
    "stage",
    "input_sha256",
    "candidate_assessments",
    "provisional_findings",
    "plausible_risks",
    "temporary_control_candidates",
    "preserved_variant_ids",
}
CONFIRMATION_ASSESSMENT_FIELDS = {
    "candidate_ids",
    "disposition",
    "reason",
    "evidence_refs",
}
CONFIRMATION_FINDING_FIELDS = {
    "id",
    "title",
    "problem_summary",
    "waste_kind",
    "candidate_ids",
    "affected_call_ids",
    "evidence_refs",
    "evidence_narrative",
    "producer_type",
    "producer_owner",
    "proposed_durable_control",
    "implementation_status",
    "targeted_verification",
    "observed_avoidable_call_count",
    "recurrence",
    "confidence",
    "complexity",
    "one_time_implementation_cost",
    "helper_categories",
    "contributing_surfaces",
}
CONFIRMATION_RISK_FIELDS = {
    "id",
    "description",
    "candidate_ids",
    "affected_call_ids",
    "evidence_refs",
    "competing_explanations",
    "missing_fact",
    "verification_needed",
}
CONFIRMATION_CHILD_ASSESSMENT_FIELDS = CONFIRMATION_ASSESSMENT_FIELDS | {
    "confirmed_findings",
    "plausible_risks",
}
CONFIRMATION_CHILD_FINDING_FIELDS = CONFIRMATION_FINDING_FIELDS - {
    "candidate_ids",
    "affected_call_ids",
}
CONFIRMATION_CHILD_RISK_FIELDS = CONFIRMATION_RISK_FIELDS - {
    "candidate_ids",
    "affected_call_ids",
}
TEMPORARY_REVIEW_FIELDS = {
    "id",
    "problem_solved",
    "affected_call_ids",
    "observed_temporary_control",
    "final_canonical_evidence_refs",
    "disposition",
    "owning_producer",
    "recurrence_inputs",
    "savings_inputs",
    "finding_id",
    "no_finding_reason",
}
TEMPORARY_CONTRIBUTION_FIELDS = {
    "id",
    "temporary_control_id",
    "owner_key",
    "control_key",
    "candidate_ids",
    "evidence_refs",
    "contribution",
    "material_variant_id",
}
CONFIRMATION_RESULT_FIELDS = {
    "schema",
    "analysis_id",
    "task_id",
    "surface_id",
    "input_sha256",
    "candidate_assessments",
    "confirmed_findings",
    "plausible_risks",
    "temporary_control_reviews",
    "temporary_control_contributions",
    "helper_category_reviews",
}
CONFIRMATION_CHILD_RESULT_FIELDS = CONFIRMATION_RESULT_FIELDS - {
    "confirmed_findings",
    "plausible_risks",
}
SYNTHESIS_RESULT_FIELDS = {
    "schema",
    "analysis_id",
    "task_id",
    "input_sha256",
    "finding_groups",
    "risk_order",
    "temporary_control_merges",
    "call_classifications",
    "producer_groups",
    "analysis_summary",
}


def _closed_result(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        missing = sorted(fields - set(value))
        extra = sorted(set(value) - fields)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unknown " + ", ".join(extra))
        raise CreditAnalysisError(f"{label} fields are invalid: {'; '.join(detail)}")




def _result_deduped_strings(
    value: Any, label: str, *, empty: bool = False
) -> list[str]:
    """Normalize only exact duplicate descriptive strings while preserving order."""

    if (
        not isinstance(value, list)
        or (not empty and not value)
        or not all(isinstance(item, str) and item for item in value)
    ):
        qualifier = "string list" if empty else "nonempty string list"
        raise CreditAnalysisError(f"{label} must be a {qualifier}")
    return list(dict.fromkeys(value))


def _result_objects(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise CreditAnalysisError(f"{label} must be an object list")
    return list(value)
















def _validate_recurrence_inputs(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CreditAnalysisError(f"{label} must be an object")
    required = {
        "calls_saved_per_affected_run",
        "additional_recurring_calls_per_affected_run",
        "affected_similar_run_frequency",
        "affected_similar_run_frequency_range",
        "estimated_calls_saved_per_similar_run",
        "assumptions",
    }
    _closed_result(value, required, label)
    for key in (
        "calls_saved_per_affected_run",
        "additional_recurring_calls_per_affected_run",
        "affected_similar_run_frequency",
        "estimated_calls_saved_per_similar_run",
    ):
        _number(value.get(key), f"{label} {key}")
    frequency_range = value.get("affected_similar_run_frequency_range")
    if (
        not isinstance(frequency_range, list)
        or len(frequency_range) != 2
        or any(not isinstance(item, (int, float)) for item in frequency_range)
        or frequency_range[0] < 0
        or frequency_range[1] < frequency_range[0]
    ):
        raise CreditAnalysisError(f"{label} frequency range is invalid")
    assumptions = _result_deduped_strings(
        value.get("assumptions"), f"{label} assumptions"
    )
    return {**value, "assumptions": assumptions}








FINDING_GROUP_FIELDS = {
    "canonical_finding_id",
    "source_finding_ids",
    "primary_source_finding_id",
    "title",
    "problem_summary",
    "owner_key",
    "control_key",
    "contributing_surfaces",
    "savings_source_finding_id",
}
TEMPORARY_MERGE_FIELDS = {
    "merge_id",
    "owner_key",
    "control_key",
    "review_ids",
    "contribution_ids",
    "disposition",
    "finding_id",
    "no_finding_reason",
    "contributing_surfaces",
}
CALL_CLASSIFICATION_FIELDS = {
    "classification",
    "call_ids",
    "primary_finding_id",
    "reason_code",
    "reason",
}
ORCHESTRATION_PRODUCER_GROUP_FIELDS = {
    "id",
    "producer_type",
    "owner",
    "finding_ids",
    "recommended_control",
    "targeted_verification",
}
ANALYSIS_SUMMARY_FIELDS = {
    "confirmed_count",
    "risk_count",
    "necessary_calls",
    "protocol_overhead_calls",
    "reviewed_no_confirmed_waste_calls",
    "unassessed_calls",
    "avoidable_calls",
    "meaningful_input_output_findings",
}












def _write_or_verify_task_input(path: pathlib.Path, payload: Mapping[str, Any]) -> str:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise CreditAnalysisError("model task input path is invalid")
        existing = _read_json(path, "model task input")
        if existing != payload:
            raise CreditAnalysisError("model task input changed across resume")
    else:
        _exclusive_json(path, payload, "model task input")
    return _file_hash(path)










def _surface_reference_text(surface_id: str, contract: Mapping[str, Any]) -> str:
    reference = next(
        item["reference"] for item in contract["surfaces"] if item["id"] == surface_id
    )
    return (SKILL_DIR / reference).read_text(encoding="utf-8")




def _write_or_verify_text(path: pathlib.Path, text_value: str, label: str) -> str:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise CreditAnalysisError(f"{label} path is invalid")
        if path.read_text(encoding="utf-8") != text_value:
            raise CreditAnalysisError(f"{label} changed across resume")
    else:
        _exclusive_text(path, text_value, label)
    return _file_hash(path)








def _jsonl_event_summary(path: pathlib.Path) -> dict[str, Any]:
    """Summarize child events without emitting their model-visible payloads."""

    event_types: Counter[str] = Counter()
    usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    malformed = 0
    child_session_ids: list[str] = []
    if not path.exists():
        return {
            "events": 0,
            "event_types": {},
            "usage": usage,
            "malformed": 0,
            "child_session_ids": [],
        }
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(item, Mapping):
                malformed += 1
                continue
            for candidate_key in ("thread_id", "session_id"):
                candidate_id = item.get(candidate_key)
                if isinstance(candidate_id, str) and candidate_id:
                    child_session_ids.append(candidate_id)
            thread = item.get("thread")
            if isinstance(thread, Mapping):
                candidate_id = thread.get("id") or thread.get("thread_id")
                if isinstance(candidate_id, str) and candidate_id:
                    child_session_ids.append(candidate_id)
            event_type = item.get("type")
            event_types[str(event_type or "unknown")] += 1
            candidates = [item]
            if isinstance(item.get("usage"), Mapping):
                candidates.append(item["usage"])
            if isinstance(item.get("turn"), Mapping):
                candidates.append(item["turn"])
                if isinstance(item["turn"].get("usage"), Mapping):
                    candidates.append(item["turn"]["usage"])
            for candidate in candidates:
                for key in usage:
                    value = candidate.get(key)
                    if isinstance(value, int) and not isinstance(value, bool):
                        usage[key] = max(usage[key], value)
    return {
        "events": sum(event_types.values()),
        "event_types": dict(sorted(event_types.items())),
        "usage": usage,
        "malformed": malformed,
        "child_session_ids": list(dict.fromkeys(child_session_ids)),
    }


def _codex_child_command(
    *,
    executable: str,
    model: str,
    reasoning_effort: str = "max",
    schema_path: pathlib.Path,
    raw_output: pathlib.Path,
    orchestration_root: pathlib.Path,
) -> list[str]:
    """Build the current CLI command with global approval policy before `exec`."""

    return [
        executable,
        "--ask-for-approval",
        "never",
        "--config",
        f'model_reasoning_effort="{reasoning_effort}"',
        "exec",
        "--model",
        model,
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "--output-schema",
        str(schema_path),
        "--color",
        "never",
        "--json",
        "--output-last-message",
        str(raw_output),
        "--cd",
        str(orchestration_root),
        "-",
    ]


def _process_is_alive(process_id: int) -> bool:
    """Check the controller parent without launching another process."""

    if process_id <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(process_id, 0)
        except OSError:
            return False
        return True
    try:
        import ctypes

        ctypes_module: Any = ctypes
        windll = ctypes_module.windll
        kernel32 = windll.kernel32
        synchronize = 0x00100000
        handle = kernel32.OpenProcess(synchronize, False, process_id)
        if not handle:
            return False
        try:
            wait_timeout = 0x00000102
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError):
        return True


def _terminate_process_tree(process: subprocess.Popen[Any]) -> int | None:
    """Terminate the exact Codex subprocess tree and wait for its exit."""

    if process.poll() is not None:
        return process.returncode
    os_module: Any = os
    signal_module: Any = signal
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os_module.killpg(process.pid, signal_module.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()
        try:
            return process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os_module.killpg(process.pid, signal_module.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
    try:
        return process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=10)


def _run_codex_child(
    *,
    analysis_id: str,
    model: str,
    reasoning_effort: str = "max",
    task: Mapping[str, Any],
    prompt_path: pathlib.Path,
    schema_path: pathlib.Path,
    attempt_dir: pathlib.Path,
    orchestration_root: pathlib.Path,
    timeout_seconds: int = 1800,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Launch one explicit, ephemeral, read-only Codex child and wait internally."""

    executable = shutil.which("codex")
    if executable is None:
        raise CreditAnalysisError("Codex CLI is unavailable")
    attempt_dir.mkdir(parents=True, exist_ok=False)
    raw_output = attempt_dir / "last-message.json"
    events_path = attempt_dir / "events.jsonl"
    stderr_path = attempt_dir / "stderr.log"
    command = _codex_child_command(
        executable=executable,
        model=model,
        reasoning_effort=reasoning_effort,
        schema_path=schema_path,
        raw_output=raw_output,
        orchestration_root=orchestration_root,
    )
    started = time.monotonic()
    child_environment = os.environ.copy()
    child_environment["CERATOPS_CREDIT_ANALYSIS_ID"] = analysis_id
    child_environment["CERATOPS_CREDIT_ANALYSIS_TASK_ID"] = str(task["task_id"])
    child_environment["CERATOPS_CREDIT_ANALYSIS_EPHEMERAL"] = "1"
    controller_parent_pid = os.getppid()
    timed_out = False
    terminated = False
    exit_code: int | None = None
    launch_error: str | None = None
    with prompt_path.open("r", encoding="utf-8") as prompt_handle, events_path.open(
        "x", encoding="utf-8", newline="\n"
    ) as events_handle, stderr_path.open("x", encoding="utf-8", newline="\n") as error_handle:
        try:
            popen_options: dict[str, Any] = {}
            if os.name == "nt":
                popen_options["creationflags"] = getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
                )
            else:
                popen_options["start_new_session"] = True
            process = subprocess.Popen(
                command,
                cwd=orchestration_root,
                stdin=prompt_handle,
                stdout=events_handle,
                stderr=error_handle,
                text=True,
                env=child_environment,
                **popen_options,
            )
        except OSError as exc:
            launch_error = f"could not launch Codex child: {exc}"
            error_handle.write(launch_error + "\n")
        else:
            last_notification = started
            try:
                while True:
                    exit_code = process.poll()
                    if exit_code is not None:
                        break
                    now = time.monotonic()
                    if not _process_is_alive(controller_parent_pid):
                        terminated = True
                        exit_code = _terminate_process_tree(process)
                        launch_error = "controller parent exited while the model was running"
                        break
                    if now - started >= timeout_seconds:
                        timed_out = True
                        terminated = True
                        exit_code = _terminate_process_tree(process)
                        break
                    if now - last_notification >= MODEL_PROGRESS_SECONDS:
                        print(
                            f"progress: waiting for {task['task_id']} on {model} "
                            f"({int(now - started)}s)",
                            file=sys.stderr,
                            flush=True,
                        )
                        last_notification = now
                    time.sleep(1)
            except BaseException:
                terminated = True
                _terminate_process_tree(process)
                raise
    duration_ms = int((time.monotonic() - started) * 1000)
    event_summary = _jsonl_event_summary(events_path)
    attempt = {
        "runner": "codex-cli",
        "model": model,
        "reasoning_effort": reasoning_effort,
        "model_invoked": launch_error is None,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "terminated": terminated,
        "duration_ms": duration_ms,
        "prompt_path": str(prompt_path),
        "schema_path": str(schema_path),
        "raw_output_path": str(raw_output),
        "events_path": str(events_path),
        "stderr_path": str(stderr_path),
        "event_summary": event_summary,
        "error": launch_error,
    }
    if launch_error is not None:
        return None, attempt
    if exit_code != 0:
        detail = ""
        if stderr_path.exists():
            detail = " ".join(stderr_path.read_text(encoding="utf-8").split())[:800]
        attempt["error"] = (
            f"Codex child failed for {task['task_id']} with exit {exit_code}"
            + (f": {detail}" if detail else "")
        )
        return None, attempt
    if not raw_output.is_file() or raw_output.is_symlink():
        attempt["error"] = f"Codex child produced no result: {task['task_id']}"
        return None, attempt
    try:
        value = json.loads(raw_output.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        attempt["error"] = f"Codex child result is not JSON: {task['task_id']}"
        attempt["json_error"] = str(exc)
        return None, attempt
    if not isinstance(value, dict):
        attempt["error"] = f"Codex child result is not an object: {task['task_id']}"
        return None, attempt
    return value, attempt


def _invoke_injected_runner(
    runner: Any,
    *,
    model: str,
    task: Mapping[str, Any],
    prompt_path: pathlib.Path,
    schema_path: pathlib.Path,
    input_payload: Mapping[str, Any],
    input_sha256: str,
    attempt_dir: pathlib.Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Invoke one in-process fake runner used by existing behavior tests."""

    if not callable(getattr(runner, "run", None)):
        raise CreditAnalysisError("injected model runner lacks run()")
    attempt_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    error: str | None = None
    try:
        value = runner.run(
            model=model,
            task=dict(task),
            prompt=prompt_path.read_text(encoding="utf-8"),
            schema=_read_json(schema_path, "model output schema"),
            input_payload=dict(input_payload),
            input_sha256=input_sha256,
        )
    except Exception as exc:  # noqa: BLE001 - fake-runner failures exercise resume.
        value = None
        error = f"injected model runner failed: {exc}"
    duration_ms = int((time.monotonic() - started) * 1000)
    raw_path = attempt_dir / "last-message.json"
    if isinstance(value, Mapping):
        _exclusive_json(raw_path, dict(value), "injected runner output")
    elif error is None:
        error = "injected model runner returned a non-object"
    events_path = attempt_dir / "events.jsonl"
    fake_event: dict[str, Any] = {
        "type": "fake.semantic.completed",
        "model": model,
        "task_id": task["task_id"],
    }
    usage_by_phase = getattr(runner, "usage_by_phase", None)
    if isinstance(usage_by_phase, Mapping):
        phase_usage = usage_by_phase.get(task["phase"])
        if isinstance(phase_usage, Mapping):
            fake_event["usage"] = dict(phase_usage)
    _exclusive_text(
        events_path,
        json.dumps(fake_event, separators=(",", ":"))
        + "\n",
        "injected runner events",
    )
    stderr_path = attempt_dir / "stderr.log"
    _exclusive_text(
        stderr_path,
        (error + "\n") if error is not None else "",
        "injected runner stderr",
    )
    attempt = {
        "runner": "injected",
        "model": model,
        "model_invoked": True,
        "exit_code": 0,
        "timed_out": False,
        "terminated": False,
        "duration_ms": duration_ms,
        "prompt_path": str(prompt_path),
        "schema_path": str(schema_path),
        "raw_output_path": str(raw_path),
        "events_path": str(events_path),
        "stderr_path": str(stderr_path),
        "event_summary": _jsonl_event_summary(events_path),
        "error": error,
    }
    return (dict(value) if isinstance(value, Mapping) else None), attempt






def _bind_attempt_record(
    attempt: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    attempt_number: int,
) -> dict[str, Any]:
    """Bind one child attempt to immutable identity and artifact hashes."""

    record = dict(attempt)
    record.update(
        {
            "analysis_id": state["analysis_id"],
            "task_id": task["task_id"],
            "phase": task["phase"],
            "attempt_number": attempt_number,
            "input_sha256": input_sha256,
            "outcome": "runner-error" if attempt.get("error") else "result-produced",
        }
    )
    artifact_paths = {
        "prompt": pathlib.Path(str(record["prompt_path"])),
        "schema": pathlib.Path(str(record["schema_path"])),
        "raw_output": pathlib.Path(str(record["raw_output_path"])),
        "events": pathlib.Path(str(record["events_path"])),
        "stderr": pathlib.Path(str(record["stderr_path"])),
    }
    artifacts: dict[str, dict[str, str] | None] = {}
    for label, path in artifact_paths.items():
        if path.is_file() and not path.is_symlink():
            artifacts[label] = {"path": str(path), "sha256": _file_hash(path)}
        elif label in {"prompt", "schema", "events", "stderr"}:
            raise CreditAnalysisError(f"child attempt {label} artifact is missing")
        else:
            artifacts[label] = None
    record["artifacts"] = artifacts
    return record










def _aggregate_finding_volume(
    finding: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, int]:
    calls = {str(call["call_id"]): call for call in _all_calls(evidence)}
    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "tool_argument_chars": 0,
        "tool_result_chars": 0,
    }
    for call_id in finding["affected_call_ids"]:
        call = calls[call_id]
        tokens = call.get("tokens")
        if isinstance(tokens, Mapping):
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            ):
                value = tokens.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    totals[key] += value
        for item in call.get("tool_results", []):
            if not isinstance(item, Mapping):
                continue
            totals["tool_argument_chars"] += int(item.get("argument_chars") or 0)
            totals["tool_result_chars"] += int(item.get("result_chars") or 0)
    return totals






def _cleanup_orchestration_transient(state: Mapping[str, Any]) -> None:
    cleanup = state.get("cleanup")
    if not isinstance(cleanup, Mapping) or cleanup.get("owner") != "credit-analysis-workflow":
        raise CreditAnalysisError("orchestration cleanup ownership is invalid")
    root = pathlib.Path(str(cleanup.get("transient_root"))).resolve()
    orchestration_root = pathlib.Path(state["paths"]["orchestration_root"]).resolve()
    if root.parent != orchestration_root or root.name != "transient":
        raise CreditAnalysisError("orchestration transient root is invalid")
    if root.is_symlink():
        raise CreditAnalysisError("orchestration transient root is a link")
    if root.exists():
        shutil.rmtree(root)
    if root.exists():
        raise CreditAnalysisError("orchestration transient cleanup failed")






# The holistic v4 controller deliberately lives in this owning helper. Legacy
# direct-result and batch commands above remain supported, while plan/execute
# resolve to the v4 definitions below.


def _holistic_model_specs(
    contract: Mapping[str, Any],
    available_models: set[str] | Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Validate explicit models and derive usable context from the local catalog."""

    models = contract["models"]
    efforts = contract["model_reasoning_effort"]
    if not isinstance(models, Mapping) or not isinstance(efforts, Mapping):
        raise CreditAnalysisError("holistic model contract is malformed")
    missing = [str(models[key]) for key in ("luna", "sol") if models[key] not in available_models]
    if missing:
        raise CreditAnalysisError(f"required model is unavailable: {missing[0]}")
    budget = contract["context_budget"]
    specs: dict[str, dict[str, Any]] = {}
    for role in ("luna", "sol"):
        slug = str(models[role])
        effort = str(efforts[role])
        details = available_models.get(slug) if isinstance(available_models, Mapping) else None
        if details is None:
            effective_tokens = 258_000
        else:
            supported = details.get("reasoning_efforts")
            if not isinstance(supported, set) or effort not in supported:
                raise CreditAnalysisError(
                    f"required reasoning effort is unavailable for model: {slug}"
                )
            raw_effective_tokens = details.get("effective_context_tokens")
            if not isinstance(raw_effective_tokens, int) or raw_effective_tokens < 1:
                raise CreditAnalysisError(
                    f"effective context is unavailable for model: {slug}"
                )
            effective_tokens = raw_effective_tokens
        output_reserve = int(budget[f"{role}_output_reserve_tokens"])
        evidence_tokens = (
            effective_tokens
            - int(budget["hidden_prompt_reserve_tokens"])
            - int(budget["safety_margin_tokens"])
            - output_reserve
        )
        if evidence_tokens < int(budget["minimum_evidence_tokens"]):
            raise CreditAnalysisError(
                f"effective context leaves no safe evidence budget for model: {slug}"
            )
        specs[role] = {
            "model": slug,
            "reasoning_effort": effort,
            "effective_context_tokens": effective_tokens,
            "evidence_token_budget": evidence_tokens,
            "evidence_char_budget": math.floor(
                evidence_tokens * float(budget["characters_per_token"])
            ),
            "output_reserve_tokens": output_reserve,
        }
    return specs


def _holistic_projection(
    value: Any,
    *,
    limit: int,
    surface_ids: Sequence[str],
) -> Any:
    """Keep useful bounded evidence while the complete value remains retained."""

    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    if len(serialized) <= limit:
        return {"mode": "complete", "value": value}
    segments = _shared_relevant_segments(
        serialized,
        surface_ids,
        text_limit=max(160, min(420, limit // 2)),
    )[:2]
    return {
        "mode": "retained-projection",
        "chars": len(serialized),
        "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "structured_outcome": _structured_outcome(value),
        "head": serialized[: min(300, limit // 3)],
        "relevant_segments": segments,
        "tail": serialized[-min(300, limit // 3) :],
    }


def _holistic_state_paths(value: Any) -> list[pathlib.Path]:
    """Find exact controller state paths only in structured tool output."""

    found: list[pathlib.Path] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            state_path = item.get("state_path")
            if isinstance(state_path, str) and state_path:
                resolved_text = state_path
                if resolved_text.startswith("<user-home>"):
                    resolved_text = str(pathlib.Path.home()) + resolved_text[len("<user-home>") :]
                found.append(pathlib.Path(resolved_text))
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, list):
            for nested in item:
                visit(nested)
            return
        if not isinstance(item, str) or len(item) > 2_000_000:
            return
        stripped = item.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                visit(json.loads(stripped))
            except json.JSONDecodeError:
                pass
        for match in re.finditer(r'"state_path"\s*:\s*("(?:[^"\\]|\\.)*")', item):
            try:
                candidate = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, str) and candidate:
                resolved_text = candidate
                if resolved_text.startswith("<user-home>"):
                    resolved_text = str(pathlib.Path.home()) + resolved_text[len("<user-home>") :]
                found.append(pathlib.Path(resolved_text))

    visit(value)
    return list(dict.fromkeys(found))


def _holistic_raw_state_paths_by_call(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[pathlib.Path]]:
    """Index transient structured state paths before evidence redaction.

    Raw local paths are used only to load explicitly referenced controller state
    and are never copied into retained evidence. Correlation IDs keep each path
    bound to the model call whose tool result supplied it.
    """

    indexed: dict[str, list[pathlib.Path]] = {}
    for row in rows:
        if row.get("type") != "response_item":
            continue
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            continue
        item_type = payload.get("type")
        call_id = payload.get("call_id") or payload.get("id")
        if (
            not isinstance(item_type, str)
            or not item_type.endswith("_output")
            or not isinstance(call_id, str)
            or not call_id
        ):
            continue
        paths = _holistic_state_paths(
            {
                key: item
                for key, item in payload.items()
                if key not in {"call_id", "id", "type"}
            }
        )
        if paths:
            indexed[call_id] = list(
                dict.fromkeys([*indexed.get(call_id, []), *paths])
            )
    return indexed


def _holistic_prior_analysis_activity(
    evidence: Mapping[str, Any],
    *,
    current_analysis_id: str,
    surface_ids: Sequence[str],
    text_limit: int,
    raw_state_paths_by_call: Mapping[str, Sequence[pathlib.Path]],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Load referenced earlier controller telemetry without prompt-text markers."""

    activities: list[dict[str, Any]] = []
    analysis_call_ids: set[str] = set()
    seen_analyses: set[str] = set()
    review_index = _review_record_index(evidence)
    for call in _all_calls(evidence):
        call_id = str(call["call_id"])
        review_records = [
            review_index[record_id]
            for record_id in call.get("model_review_record_ids", [])
            if record_id in review_index
        ]
        review_payloads = [record.get("content") for record in review_records]
        state_paths = _holistic_state_paths(
            [call.get("tool_results", []), *review_payloads]
        )
        for record in review_records:
            record_call_id = record.get("call_id")
            if isinstance(record_call_id, str):
                state_paths.extend(raw_state_paths_by_call.get(record_call_id, ()))
        for unresolved in dict.fromkeys(state_paths):
            try:
                state_path = unresolved.expanduser().resolve(strict=True)
            except OSError:
                continue
            if state_path.is_symlink() or not state_path.is_file():
                continue
            try:
                prior = _read_json(state_path, "referenced prior analysis state")
            except CreditAnalysisError:
                continue
            if prior.get("schema") != HOLISTIC_STATE_SCHEMA:
                continue
            analysis_id = prior.get("analysis_id")
            if not isinstance(analysis_id, str) or analysis_id == current_analysis_id:
                continue
            analysis_call_ids.add(call_id)
            if analysis_id in seen_analyses:
                continue
            seen_analyses.add(analysis_id)
            tasks: list[dict[str, Any]] = []
            execution = prior.get("execution")
            order = prior.get("task_order")
            if isinstance(execution, Mapping) and isinstance(order, list):
                for task_id in order:
                    task_state = execution.get(task_id)
                    if not isinstance(task_id, str) or not isinstance(task_state, Mapping):
                        continue
                    attempts: list[dict[str, Any]] = []
                    for attempt in task_state.get("attempts", []):
                        if not isinstance(attempt, Mapping):
                            continue
                        artifacts = attempt.get("artifacts")
                        prompt_projection = None
                        result_projection = None
                        if isinstance(artifacts, Mapping):
                            prompt_artifact = artifacts.get("prompt")
                            if isinstance(prompt_artifact, Mapping):
                                prompt_path = pathlib.Path(str(prompt_artifact.get("path", "")))
                                if prompt_path.is_file() and not prompt_path.is_symlink():
                                    prompt_projection = _holistic_projection(
                                        prompt_path.read_text(encoding="utf-8"),
                                        limit=text_limit,
                                        surface_ids=surface_ids,
                                    )
                            output_artifact = artifacts.get("raw_output")
                            if isinstance(output_artifact, Mapping):
                                output_path = pathlib.Path(str(output_artifact.get("path", "")))
                                if output_path.is_file() and not output_path.is_symlink():
                                    result_projection = _holistic_projection(
                                        output_path.read_text(encoding="utf-8"),
                                        limit=text_limit,
                                        surface_ids=surface_ids,
                                    )
                        attempts.append(
                            {
                                "attempt_number": attempt.get("attempt_number"),
                                "model": attempt.get("model"),
                                "reasoning_effort": attempt.get("reasoning_effort"),
                                "duration_ms": attempt.get("duration_ms"),
                                "exit_code": attempt.get("exit_code"),
                                "timed_out": attempt.get("timed_out"),
                                "terminated": attempt.get("terminated"),
                                "error": attempt.get("error"),
                                "event_summary": attempt.get("event_summary"),
                                "prompt": prompt_projection,
                                "result": result_projection,
                            }
                        )
                    tasks.append(
                        {
                            "task_id": task_id,
                            "status": task_state.get("status"),
                            "result_identity": task_state.get("result"),
                            "attempts": attempts,
                        }
                    )
            activities.append(
                {
                    "analysis_id": analysis_id,
                    "source_call_id": call_id,
                    "state_sha256": _file_hash(state_path),
                    "phase": prior.get("phase"),
                    "model_calls": prior.get("model_calls"),
                    "model_attempts": prior.get("model_attempts"),
                    "tasks": tasks,
                    "evidence_ref": f"analysis://{analysis_id}",
                }
            )
    return activities, analysis_call_ids


def _collect_holistic_evidence(
    *,
    request: Mapping[str, Any],
    contract: Mapping[str, Any],
    ledger: ModuleType,
    analysis_id: str,
    surface_ids: Sequence[str],
) -> tuple[dict[str, Any], str, str, list[tuple[str, str]], set[str]]:
    """Collect once, freeze lineage, and separate earlier analysis activity."""

    cutoff = dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")
    try:
        rows, source_fingerprint = ledger.load_rows_with_fingerprint(request["session"])
        raw_state_paths_by_call = _holistic_raw_state_paths_by_call(rows)
        path_roots = ledger.review_path_roots(rows)
        collected = ledger.collect_session_evidence_from_rows(
            rows,
            session=request["session"],
            source_fingerprint=source_fingerprint,
            last_runs=request["collector_window"]["last_runs"],
            completed_turn_ids=request["collector_window"]["completed_turn_ids"],
            pricing_profile=request["pricing"],
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise CreditAnalysisError(f"session collection failed: {exc}") from exc
    if collected.get("collection", {}).get("session_reads") != 1:
        raise CreditAnalysisError("session collector did not report exactly one read")
    if collected.get("collection", {}).get("model_calls", 0) < 1:
        raise CreditAnalysisError("selected completed-run window has no model calls")
    collector_schema = collected.pop("schema", None)
    evidence: dict[str, Any] = {
        **collected,
        "schema": contract["evidence_schema"],
        "collector_schema": collector_schema,
        "analysis_id": analysis_id,
        "source": request["source"],
        "requested_window": request["window"],
        "surface_contract_version": contract["surface_contract_version"],
        "surface_contract_hash": _file_hash(CONTRACT_PATH),
        "mutation_authority": False,
    }
    prior_activity, analysis_call_ids = _holistic_prior_analysis_activity(
        evidence,
        current_analysis_id=analysis_id,
        surface_ids=surface_ids,
        text_limit=int(contract["chunking"]["compact_text_chars"]),
        raw_state_paths_by_call=raw_state_paths_by_call,
    )
    evidence["analysis_generated_activity"] = prior_activity
    evidence["analysis_lineage"] = {
        "controller_analysis_id": analysis_id,
        "source_session": str(request["session"]),
        "source_fingerprint": source_fingerprint,
        "collection_cutoff_utc": cutoff,
        "included_prior_analysis_ids": [item["analysis_id"] for item in prior_activity],
        "excluded_own_descendant_task_ids": [],
        "source_selection_uses_prompt_markers": False,
        "execution_recollects_session": False,
        "producer_and_analysis_work_are_separate": True,
    }
    fingerprint = _content_hash(evidence)
    evidence["evidence_fingerprint"] = fingerprint
    evidence_path = pathlib.Path(request["evidence_path"])
    _exclusive_json(evidence_path, evidence, "retained evidence")
    return evidence, fingerprint, _file_hash(evidence_path), path_roots, analysis_call_ids


def _holistic_compact_bundle(
    *,
    analysis_id: str,
    evidence: Mapping[str, Any],
    evidence_path: pathlib.Path,
    canonical_state: Mapping[str, Mapping[str, Any]],
    contract: Mapping[str, Any],
    surface_order: Sequence[str],
    analysis_call_ids: set[str],
) -> dict[str, Any]:
    """Format every selected call once as compact, causally usable evidence."""

    calls = _all_calls(evidence)
    selected_by_surface = {
        surface: set(_candidate_ids(surface, evidence, contract))
        for surface in surface_order
    }
    selected_calls = [
        call
        for call in calls
        if any(str(call["call_id"]) in selected_by_surface[s] for s in surface_order)
    ]
    if not selected_calls:
        raise CreditAnalysisError("holistic evidence has no selected calls")
    canonical_by_observed = {
        str(observed): canonical
        for canonical, record in canonical_state.items()
        for observed in record.get("observed_references", [canonical])
    }
    review_index = _review_record_index(evidence)
    run_index = _run_index(evidence)
    limit = int(contract["chunking"]["compact_text_chars"])
    records: list[dict[str, Any]] = []
    for ordinal, call in enumerate(selected_calls, start=1):
        call_id = str(call["call_id"])
        turn_id = str(call["turn_id"])
        run = run_index.get(turn_id)
        if run is None:
            raise CreditAnalysisError("selected call has no run")
        surfaces = [
            surface for surface in surface_order if call_id in selected_by_surface[surface]
        ]
        message_ids = [str(value) for value in call.get("user_message_ids", [])]
        messages = [
            {
                "message_id": str(message["message_id"]),
                "timestamp": message.get("timestamp"),
                "text": _holistic_projection(
                    message.get("text", ""),
                    limit=limit,
                    surface_ids=surfaces,
                ),
                "evidence_ref": f"evidence://user-messages/{message['message_id']}",
            }
            for message in run.get("user_messages", [])
            if isinstance(message, Mapping) and str(message.get("message_id")) in message_ids
        ]
        if {item["message_id"] for item in messages} != set(message_ids):
            raise CreditAnalysisError("selected call user-message evidence is missing")
        review_records: list[dict[str, Any]] = []
        artifact_refs: list[str] = []
        for record_id in call.get("model_review_record_ids", []):
            raw = review_index.get(str(record_id))
            if raw is None:
                raise CreditAnalysisError("selected call review evidence is missing")
            content = raw.get("content")
            serialized = json.dumps(content, ensure_ascii=False, default=str)
            artifact_refs.extend(_canonical_artifact_references(serialized))
            review_records.append(
                {
                    "record_id": str(record_id),
                    "kind": raw.get("kind"),
                    "name": raw.get("name"),
                    "timestamp": raw.get("timestamp"),
                    "content": _holistic_projection(
                        content,
                        limit=limit,
                        surface_ids=surfaces,
                    ),
                    "evidence_ref": f"evidence://review/{record_id}",
                }
            )
        repeated_groups = [
            group
            for group in evidence.get("repeated_tool_calls", [])
            if isinstance(group, Mapping)
            and any(
                isinstance(item, Mapping)
                and item.get("fingerprint") == group.get("fingerprint")
                for item in call.get("tool_results", [])
            )
        ]
        volume = {
            "tokens": call.get("tokens"),
            "estimated_credit_cost": call.get("estimated_credit_cost"),
            "tool_argument_chars": sum(
                int(item.get("argument_chars") or 0)
                for item in call.get("tool_results", [])
                if isinstance(item, Mapping)
            ),
            "tool_result_chars": sum(
                int(item.get("result_chars") or 0)
                for item in call.get("tool_results", [])
                if isinstance(item, Mapping)
            ),
        }
        signals = _observable_high_signal_reasons(
            call=call,
            messages=messages,
            records=review_records,
            repeated_groups=repeated_groups,
            volume=volume,
        )
        candidate_id = f"{analysis_id}.c.{ordinal:06d}"
        records.append(
            {
                "candidate_id": candidate_id,
                "candidate_ordinal": ordinal,
                "call_id": call_id,
                "turn_id": turn_id,
                "model_call_index": call.get("index"),
                "timestamp": call.get("timestamp"),
                "workstream": (
                    "analysis-overhead" if call_id in analysis_call_ids else "producer"
                ),
                "surface_lenses": surfaces,
                "user_messages": messages,
                "assistant_and_tool_evidence": review_records,
                "actions": _holistic_projection(
                    call.get("actions", []), limit=limit, surface_ids=surfaces
                ),
                "semantic_actions": _holistic_projection(
                    call.get("semantic_actions", []), limit=limit, surface_ids=surfaces
                ),
                "tool_results": [
                    _holistic_projection(item, limit=limit, surface_ids=surfaces)
                    for item in call.get("tool_results", [])
                ],
                "run_telemetry": {
                    "duration_ms": call.get("run_duration_ms"),
                    "totals": run.get("totals"),
                    "tool_counts": run.get("tool_counts"),
                },
                "volume": volume,
                "high_signal_reasons": signals,
                "canonical_artifact_references": list(
                    dict.fromkeys(
                        canonical_by_observed.get(reference, reference)
                        for reference in artifact_refs
                    )
                ),
                "repeated_action_groups": repeated_groups,
                "evidence_refs": [
                    f"evidence://calls/{call_id}",
                    *[item["evidence_ref"] for item in messages],
                    *[item["evidence_ref"] for item in review_records],
                ],
            }
        )
    canonical_index = [
        {
            "artifact_reference": reference,
            "source_reference_count": record.get("source_reference_count"),
            "locations": record.get("locations", []),
            "evidence_ref": record.get("evidence_ref"),
            "status": record.get("status"),
            "kind": record.get("kind"),
            "source_bytes": record.get("source_bytes"),
            "source_sha256": record.get("source_sha256"),
            "projection": _holistic_projection(
                record.get("projection"),
                limit=limit,
                surface_ids=surface_order,
            ),
        }
        for reference, record in canonical_state.items()
    ]
    return {
        "schema": HOLISTIC_EVIDENCE_SCHEMA,
        "analysis_id": analysis_id,
        "retained_evidence_path": str(evidence_path),
        "analysis_policy": _analysis_policy(contract),
        "surface_order": list(surface_order),
        "candidate_ids": [record["candidate_id"] for record in records],
        "call_ids": [record["call_id"] for record in records],
        "records": records,
        "canonical_state": canonical_index,
        "analysis_generated_activity": evidence["analysis_generated_activity"],
    }


def _holistic_episodes(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Group adjacent calls by turn while deduplicating each user message once."""

    episodes: list[dict[str, Any]] = []
    current: list[Mapping[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        messages: dict[str, Mapping[str, Any]] = {}
        calls: list[dict[str, Any]] = []
        for record in current:
            for message in record["user_messages"]:
                messages.setdefault(str(message["message_id"]), message)
            call = dict(record)
            call["user_message_ids"] = [
                str(message["message_id"]) for message in record["user_messages"]
            ]
            call.pop("user_messages", None)
            calls.append(call)
        episodes.append(
            {
                "episode_id": f"episode.{len(episodes) + 1:06d}",
                "turn_id": str(current[0]["turn_id"]),
                "candidate_ids": [str(call["candidate_id"]) for call in calls],
                "user_messages": list(messages.values()),
                "calls": calls,
            }
        )

    for record in bundle["records"]:
        if current and str(current[-1]["turn_id"]) != str(record["turn_id"]):
            flush()
            current = []
        current.append(record)
    flush()
    observed = [candidate for episode in episodes for candidate in episode["candidate_ids"]]
    if observed != bundle["candidate_ids"] or len(observed) != len(set(observed)):
        raise CreditAnalysisError("holistic episodes changed call coverage or order")
    return episodes


def _holistic_luna_payload(
    *,
    analysis_id: str,
    task_id: str,
    ordinal: int,
    episodes: Sequence[Mapping[str, Any]],
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    candidate_ids = [candidate for episode in episodes for candidate in episode["candidate_ids"]]
    record_ids = set(candidate_ids)
    return {
        "schema": HOLISTIC_TASK_SCHEMA,
        "analysis_id": analysis_id,
        "task_id": task_id,
        "phase": "luna-discovery",
        "packet_ordinal": ordinal,
        "surface_order": bundle["surface_order"],
        "analysis_policy": bundle["analysis_policy"],
        "candidate_ids": candidate_ids,
        "candidate_ids_sha256": _content_hash(candidate_ids),
        "episodes": list(episodes),
        "canonical_state": bundle["canonical_state"],
        "analysis_generated_activity": bundle["analysis_generated_activity"],
        "coverage_contract": {
            "each_candidate_in_exactly_one_luna_packet": True,
            "sparse_discovery_not_candidate_surface_classification": True,
        },
        "workstream_counts": dict(
            Counter(
                record["workstream"]
                for record in bundle["records"]
                if record["candidate_id"] in record_ids
            )
        ),
    }


def _holistic_split_episode(
    episode: Mapping[str, Any],
    *,
    analysis_id: str,
    budget_chars: int,
    bundle: Mapping[str, Any],
) -> list[dict[str, Any]]:
    calls = list(episode["calls"])
    fragments: list[list[Mapping[str, Any]]] = []
    current: list[Mapping[str, Any]] = []
    for call in calls:
        proposed = [*current, call]
        probe = {
            **episode,
            "candidate_ids": [str(item["candidate_id"]) for item in proposed],
            "calls": proposed,
        }
        payload = _holistic_luna_payload(
            analysis_id=analysis_id,
            task_id="luna.discovery.0001",
            ordinal=1,
            episodes=[probe],
            bundle=bundle,
        )
        if current and _json_chars(payload) > budget_chars:
            fragments.append(current)
            current = [call]
        else:
            current = proposed
        single = {
            **episode,
            "candidate_ids": [str(item["candidate_id"]) for item in current],
            "calls": current,
        }
        if _json_chars(
            _holistic_luna_payload(
                analysis_id=analysis_id,
                task_id="luna.discovery.0001",
                ordinal=1,
                episodes=[single],
                bundle=bundle,
            )
        ) > budget_chars:
            raise CreditAnalysisError(
                f"one compact call exceeds the Luna context budget: {call['candidate_id']}"
            )
    if current:
        fragments.append(current)
    result: list[dict[str, Any]] = []
    for index, group in enumerate(fragments, start=1):
        result.append(
            {
                **episode,
                "episode_fragment": index,
                "episode_fragment_count": len(fragments),
                "candidate_ids": [str(call["candidate_id"]) for call in group],
                "calls": list(group),
            }
        )
    return result


def _holistic_partition(
    *,
    analysis_id: str,
    episodes: Sequence[Mapping[str, Any]],
    bundle: Mapping[str, Any],
    budget_chars: int,
) -> list[list[dict[str, Any]]]:
    """Make the minimum greedy ordered shared partition, never one per surface."""

    fragments: list[dict[str, Any]] = []
    for episode in episodes:
        probe = _holistic_luna_payload(
            analysis_id=analysis_id,
            task_id="luna.discovery.0001",
            ordinal=1,
            episodes=[episode],
            bundle=bundle,
        )
        if _json_chars(probe) <= budget_chars:
            fragments.append(dict(episode))
        else:
            fragments.extend(
                _holistic_split_episode(
                    episode,
                    analysis_id=analysis_id,
                    budget_chars=budget_chars,
                    bundle=bundle,
                )
            )
    packets: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for fragment in fragments:
        proposed = [*current, fragment]
        ordinal = len(packets) + 1
        payload = _holistic_luna_payload(
            analysis_id=analysis_id,
            task_id=f"luna.discovery.{ordinal:04d}",
            ordinal=ordinal,
            episodes=proposed,
            bundle=bundle,
        )
        if current and _json_chars(payload) > budget_chars:
            packets.append(current)
            current = [fragment]
        else:
            current = proposed
    if current:
        packets.append(current)
    if not packets:
        raise CreditAnalysisError("holistic Luna plan is empty")
    observed = [candidate for packet in packets for episode in packet for candidate in episode["candidate_ids"]]
    if observed != bundle["candidate_ids"] or len(observed) != len(set(observed)):
        raise CreditAnalysisError("holistic Luna partition changed call coverage")
    return packets


def _validate_holistic_manifest(
    manifest: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    expected_packets: Sequence[Sequence[Mapping[str, Any]]] | None = None,
) -> None:
    if manifest.get("schema") != HOLISTIC_MANIFEST_SCHEMA:
        raise CreditAnalysisError("holistic manifest schema is invalid")
    tasks = manifest.get("luna_tasks")
    if not isinstance(tasks, list) or not tasks:
        raise CreditAnalysisError("holistic manifest has no Luna tasks")
    expected = list(manifest.get("candidate_ids", []))
    observed = [candidate for task in tasks for candidate in task.get("candidate_ids", [])]
    if observed != expected or len(observed) != len(set(observed)):
        raise CreditAnalysisError("holistic manifest coverage is missing or duplicated")
    if expected_packets is not None:
        expected_membership = [
            [
                candidate
                for episode in packet
                for candidate in episode["candidate_ids"]
            ]
            for packet in expected_packets
        ]
        observed_membership = [list(task.get("candidate_ids", [])) for task in tasks]
        if observed_membership != expected_membership:
            raise CreditAnalysisError(
                "holistic manifest packet boundaries do not match the minimum "
                "ordered partition"
            )
    if manifest.get("projected_luna_calls") != len(tasks):
        raise CreditAnalysisError("projected Luna count is invalid")
    if manifest.get("projected_sol_calls") != 1:
        raise CreditAnalysisError("holistic analysis must project one Sol call")
    if manifest.get("projected_semantic_calls") != len(tasks) + 1:
        raise CreditAnalysisError("projected semantic count is invalid")
    if manifest.get("surface_order") not in (
        contract["surface_order"],
        [manifest.get("action")],
    ):
        raise CreditAnalysisError("holistic manifest surface order is invalid")
    if manifest.get("sol_task", {}).get("dependencies") != [
        task["task_id"] for task in tasks
    ]:
        raise CreditAnalysisError("Sol task does not depend on every Luna packet")


def _holistic_public_status(state: Mapping[str, Any]) -> dict[str, Any]:
    task_order = state["task_order"]
    execution = state["execution"]
    completed = sum(1 for task_id in task_order if execution[task_id]["status"] == "complete")
    manifest = state["manifest"]
    final = state.get("final_result")
    return {
        "schema": HOLISTIC_STATE_SCHEMA,
        "analysis_id": state["analysis_id"],
        "phase": state["phase"],
        "complete": state["phase"] == "complete",
        "state_path": state["paths"]["state"],
        "manifest_path": manifest["path"],
        "evidence_path": state["evidence"]["path"],
        "final_result_path": final.get("path") if isinstance(final, Mapping) else None,
        "report_path": final.get("report_path") if isinstance(final, Mapping) else None,
        "projected_luna_calls": manifest["projected_luna_calls"],
        "projected_sol_calls": 1,
        "projected_semantic_calls": manifest["projected_semantic_calls"],
        "shared_luna_packets": len(manifest["luna_tasks"]),
        "shared_candidate_count": len(manifest["candidate_ids"]),
        "actual_luna_calls": state["model_attempts"]["luna"],
        "actual_sol_calls": state["model_attempts"]["sol"],
        "accepted_luna_calls": state["model_calls"]["luna"],
        "accepted_sol_calls": state["model_calls"]["sol"],
        "completed_tasks": completed,
        "total_tasks": len(task_order),
        "next_task": next(
            (task_id for task_id in task_order if execution[task_id]["status"] != "complete"),
            None,
        ),
        "included_prior_analysis_ids": state["lineage"]["included_prior_analysis_ids"],
    }


def command_plan_orchestration(
    request_path: pathlib.Path,
    *,
    available_models: set[str] | Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Collect once and freeze the finite holistic Luna-plus-Sol plan."""

    contract = _load_contract()
    catalog = _codex_model_catalog() if available_models is None else available_models
    model_specs = _holistic_model_specs(contract, catalog)
    ledger = _load_ledger()
    request = _validate_request(request_path, contract, ledger)
    surface_order = _surface_order_for_request(request, contract)
    analysis_id = secrets.token_hex(12)
    evidence, fingerprint, evidence_sha, path_roots, analysis_call_ids = (
        _collect_holistic_evidence(
            request=request,
            contract=contract,
            ledger=ledger,
            analysis_id=analysis_id,
            surface_ids=surface_order,
        )
    )
    orchestration_root = pathlib.Path(request["task_root"]) / "orchestration"
    if orchestration_root.exists() or orchestration_root.is_symlink():
        raise CreditAnalysisError("task root already contains orchestration state")
    for name in ("inputs", "prompts", "schemas", "results", "attempts", "transient"):
        (orchestration_root / name).mkdir(parents=True, exist_ok=False)
    canonical_state, canonical_record = _collect_canonical_state_snapshot(
        evidence=evidence,
        path_roots=path_roots,
        orchestration_root=orchestration_root,
        ledger=ledger,
    )
    bundle = _holistic_compact_bundle(
        analysis_id=analysis_id,
        evidence=evidence,
        evidence_path=pathlib.Path(request["evidence_path"]),
        canonical_state=canonical_state,
        contract=contract,
        surface_order=surface_order,
        analysis_call_ids=analysis_call_ids,
    )
    compact_path = orchestration_root / "compact-causal-evidence.json"
    _exclusive_json(compact_path, bundle, "compact causal evidence")
    episodes = _holistic_episodes(bundle)
    packets = _holistic_partition(
        analysis_id=analysis_id,
        episodes=episodes,
        bundle=bundle,
        budget_chars=int(model_specs["luna"]["evidence_char_budget"]),
    )
    luna_tasks: list[dict[str, Any]] = []
    for ordinal, packet in enumerate(packets, start=1):
        task_id = f"luna.discovery.{ordinal:04d}"
        payload = _holistic_luna_payload(
            analysis_id=analysis_id,
            task_id=task_id,
            ordinal=ordinal,
            episodes=packet,
            bundle=bundle,
        )
        if _json_chars(payload) > int(model_specs["luna"]["evidence_char_budget"]):
            raise CreditAnalysisError("frozen Luna packet exceeds its dynamic budget")
        artifacts = _task_artifact_paths(orchestration_root, task_id)
        input_path = pathlib.Path(artifacts["input"])
        _exclusive_json(input_path, payload, "Luna task input")
        luna_tasks.append(
            {
                "task_id": task_id,
                "phase": "luna-discovery",
                "ordinal": ordinal,
                "dependencies": [],
                "candidate_ids": payload["candidate_ids"],
                "candidate_ids_sha256": payload["candidate_ids_sha256"],
                "input_sha256": _file_hash(input_path),
                "input_chars": _json_chars(payload),
                "artifacts": artifacts,
            }
        )
    sol_task_id = "sol.adjudication"
    sol_task = {
        "task_id": sol_task_id,
        "phase": "sol-adjudication",
        "ordinal": 1,
        "dependencies": [task["task_id"] for task in luna_tasks],
        "candidate_ids": list(bundle["candidate_ids"]),
        "input_sha256": None,
        "artifacts": _task_artifact_paths(orchestration_root, sol_task_id),
    }
    manifest = {
        "schema": HOLISTIC_MANIFEST_SCHEMA,
        "analysis_id": analysis_id,
        "action": request["action"],
        "mode": request["mode"],
        "mutation_authority": False,
        "evidence_fingerprint": fingerprint,
        "source_freeze": evidence["analysis_lineage"],
        "surface_contract_version": contract["surface_contract_version"],
        "surface_order": surface_order,
        "models": {key: spec["model"] for key, spec in model_specs.items()},
        "model_specs": model_specs,
        "canonical_state": canonical_record,
        "compact_evidence": {
            "path": str(compact_path),
            "sha256": _file_hash(compact_path),
            "chars": _json_chars(bundle),
        },
        "candidate_ids": list(bundle["candidate_ids"]),
        "call_ids": list(bundle["call_ids"]),
        "candidate_ids_sha256": _content_hash(bundle["candidate_ids"]),
        "episode_count": len(episodes),
        "luna_tasks": luna_tasks,
        "sol_task": sol_task,
        "projected_luna_calls": len(luna_tasks),
        "projected_sol_calls": 1,
        "projected_semantic_calls": len(luna_tasks) + 1,
    }
    _validate_holistic_manifest(manifest, contract, expected_packets=packets)
    manifest_path = orchestration_root / "chunk-manifest.json"
    _exclusive_json(manifest_path, manifest, "holistic manifest")
    task_order = [*[task["task_id"] for task in luna_tasks], sol_task_id]
    state = {
        "schema": HOLISTIC_STATE_SCHEMA,
        "version": 4,
        "analysis_id": analysis_id,
        "action": request["action"],
        "mode": request["mode"],
        "mutation_authority": False,
        "phase": "planned",
        "surface_contract_version": contract["surface_contract_version"],
        "models": manifest["models"],
        "model_specs": model_specs,
        "lineage": evidence["analysis_lineage"],
        "source": {
            **request["source"],
            "resolved_session": str(request["session"]),
            "fingerprint": evidence["source_fingerprint"],
            "collection_cutoff_utc": evidence["analysis_lineage"]["collection_cutoff_utc"],
        },
        "window": {
            "requested": request["window"],
            "resolved": evidence["window"],
            "fingerprint": evidence["window_fingerprint"],
        },
        "evidence": {
            "path": str(request["evidence_path"]),
            "fingerprint": fingerprint,
            "sha256": evidence_sha,
            "session_reads": 1,
        },
        "manifest": {**manifest, "path": str(manifest_path), "sha256": _file_hash(manifest_path)},
        "immutable_artifacts": {
            "request": {"path": str(request["request_path"]), "sha256": request["request_hash"]},
            "surface_contract": {"path": str(CONTRACT_PATH), "sha256": _file_hash(CONTRACT_PATH)},
            "evidence": {"path": str(request["evidence_path"]), "sha256": evidence_sha},
            "manifest": {"path": str(manifest_path), "sha256": _file_hash(manifest_path)},
            "compact_evidence": manifest["compact_evidence"],
            "canonical_state": canonical_record,
        },
        "task_order": task_order,
        "execution": {
            task_id: {"status": "pending", "attempts": [], "result": None}
            for task_id in task_order
        },
        "model_calls": {"luna": 0, "sol": 0},
        "model_attempts": {"luna": 0, "sol": 0},
        "child_lineage": [],
        "paths": {
            "state": str(request["state_path"]),
            "orchestration_root": str(orchestration_root),
            "transient": str(orchestration_root / "transient"),
            "final_result": request["paths"]["final_result"],
            "report": str(pathlib.Path(request["task_root"]) / "final-report.md"),
        },
        "cleanup": {
            "owner": "credit-analysis-workflow",
            "trigger": "successful-finalization",
            "transient_root": str(orchestration_root / "transient"),
        },
        "final_result": None,
    }
    _exclusive_json(pathlib.Path(request["state_path"]), state, "holistic state")
    return _holistic_public_status(state)


def _holistic_task_map(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    tasks = [*manifest["luna_tasks"], manifest["sol_task"]]
    result = {str(task["task_id"]): dict(task) for task in tasks}
    if len(result) != len(tasks):
        raise CreditAnalysisError("holistic task IDs are duplicated")
    return result


def _holistic_save_state(state: Mapping[str, Any]) -> None:
    _atomic_json(pathlib.Path(str(state["paths"]["state"])), state, "holistic state")


def _holistic_read_state(
    state_path: pathlib.Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Reopen immutable controller state without recollecting the source session."""

    resolved = state_path.expanduser().resolve(strict=True)
    if resolved.is_symlink() or not resolved.is_file():
        raise CreditAnalysisError("holistic state path is invalid")
    state = _read_json(resolved, "holistic state")
    if state.get("schema") != HOLISTIC_STATE_SCHEMA or state.get("version") != 4:
        raise CreditAnalysisError("holistic state schema is invalid")
    if pathlib.Path(str(state.get("paths", {}).get("state"))).resolve() != resolved:
        raise CreditAnalysisError("holistic state identity changed")
    if state.get("mutation_authority") is not False:
        raise CreditAnalysisError("holistic state mutation authority changed")
    contract = _load_contract()
    if state.get("surface_contract_version") != contract["surface_contract_version"]:
        raise CreditAnalysisError("holistic state contract version changed")
    immutable = state.get("immutable_artifacts")
    if not isinstance(immutable, Mapping):
        raise CreditAnalysisError("holistic immutable artifact index is invalid")
    for label in ("request", "surface_contract", "evidence", "manifest", "compact_evidence"):
        record = immutable.get(label)
        if not isinstance(record, Mapping):
            raise CreditAnalysisError(f"holistic immutable artifact is missing: {label}")
        path = pathlib.Path(str(record.get("path")))
        if path.is_symlink() or not path.is_file() or _file_hash(path) != record.get("sha256"):
            raise CreditAnalysisError(f"holistic immutable artifact changed: {label}")
    evidence = _read_json(pathlib.Path(state["evidence"]["path"]), "holistic evidence")
    if evidence.get("evidence_fingerprint") != state["evidence"]["fingerprint"]:
        raise CreditAnalysisError("holistic evidence fingerprint changed")
    manifest_path = pathlib.Path(str(state["manifest"]["path"]))
    manifest = _read_json(manifest_path, "holistic manifest")
    embedded = dict(state["manifest"])
    embedded.pop("path", None)
    embedded.pop("sha256", None)
    if manifest != embedded:
        raise CreditAnalysisError("embedded holistic manifest changed")
    compact = _read_json(
        pathlib.Path(str(manifest["compact_evidence"]["path"])),
        "compact causal evidence",
    )
    expected_packets = _holistic_partition(
        analysis_id=str(manifest["analysis_id"]),
        episodes=_holistic_episodes(compact),
        bundle=compact,
        budget_chars=int(state["model_specs"]["luna"]["evidence_char_budget"]),
    )
    _validate_holistic_manifest(
        manifest,
        contract,
        expected_packets=expected_packets,
    )
    if compact.get("schema") != HOLISTIC_EVIDENCE_SCHEMA:
        raise CreditAnalysisError("compact causal evidence schema changed")
    if compact.get("candidate_ids") != manifest["candidate_ids"]:
        raise CreditAnalysisError("compact causal evidence coverage changed")
    order = state.get("task_order")
    execution = state.get("execution")
    expected_order = [
        *[task["task_id"] for task in manifest["luna_tasks"]],
        manifest["sol_task"]["task_id"],
    ]
    if order != expected_order or not isinstance(execution, Mapping) or set(execution) != set(order):
        raise CreditAnalysisError("holistic execution queue changed")
    tasks = _holistic_task_map(manifest)
    for task_id in order:
        task = tasks[task_id]
        task_state = execution[task_id]
        if not isinstance(task_state, Mapping) or set(task_state) != {
            "status",
            "attempts",
            "result",
        }:
            raise CreditAnalysisError("holistic task state is invalid")
        if task_state["status"] not in {"pending", "complete"}:
            raise CreditAnalysisError("holistic task status is invalid")
        attempts = task_state["attempts"]
        if not isinstance(attempts, list):
            raise CreditAnalysisError("holistic attempt ledger is invalid")
        for attempt in attempts:
            if not isinstance(attempt, Mapping):
                raise CreditAnalysisError("holistic attempt record is invalid")
            artifacts = attempt.get("artifacts")
            if not isinstance(artifacts, Mapping):
                raise CreditAnalysisError("holistic attempt artifacts are invalid")
            for artifact in artifacts.values():
                if artifact is None:
                    continue
                if not isinstance(artifact, Mapping):
                    raise CreditAnalysisError("holistic attempt artifact is invalid")
                path = pathlib.Path(str(artifact.get("path")))
                if path.is_symlink() or not path.is_file() or _file_hash(path) != artifact.get("sha256"):
                    raise CreditAnalysisError("holistic attempt artifact changed")
        result = task_state["result"]
        if task_state["status"] == "complete":
            if not isinstance(result, Mapping):
                raise CreditAnalysisError("completed holistic result is missing")
            result_path = pathlib.Path(str(result.get("path")))
            if (
                result_path.is_symlink()
                or not result_path.is_file()
                or _file_hash(result_path) != result.get("sha256")
                or result.get("task_id") != task_id
            ):
                raise CreditAnalysisError("completed holistic result changed")
        elif result is not None:
            raise CreditAnalysisError("pending holistic task has a result")
        input_path = pathlib.Path(str(task["artifacts"]["input"]))
        if task_id != manifest["sol_task"]["task_id"] or input_path.exists():
            if input_path.is_symlink() or not input_path.is_file():
                raise CreditAnalysisError("holistic task input is missing")
            expected_input_hash = task.get("input_sha256")
            if expected_input_hash is not None and _file_hash(input_path) != expected_input_hash:
                raise CreditAnalysisError("holistic task input changed")
        if task["phase"] == "sol-adjudication" and input_path.exists():
            aliases = _holistic_read_sol_aliases(task, _file_hash(input_path))
            aliases_path = pathlib.Path(str(task["artifacts"]["aliases"]))
            if (
                task_state["status"] == "complete"
                and isinstance(result, Mapping)
                and result.get("aliases_sha256") != _file_hash(aliases_path)
            ):
                raise CreditAnalysisError("completed Sol alias map changed")
            if aliases.get("analysis_id") != state["analysis_id"]:
                raise CreditAnalysisError("Sol alias analysis identity changed")
    return state, evidence, contract, compact


def command_orchestration_status(state_path: pathlib.Path) -> dict[str, Any]:
    state, _, _, _ = _holistic_read_state(state_path)
    return _holistic_public_status(state)


def _holistic_result_refs(value: Any, label: str, *, empty: bool = False) -> list[str]:
    refs = _result_deduped_strings(value, label, empty=empty)
    if any(not ref.startswith(("evidence://", "analysis://")) for ref in refs):
        raise CreditAnalysisError(f"{label} contains a non-evidence reference")
    return refs


def _holistic_surface_ids(
    value: Any,
    label: str,
    surface_order: Sequence[str],
) -> list[str]:
    """Validate a surface set and normalize it to the frozen public order."""

    surfaces = _result_deduped_strings(value, label)
    if not set(surfaces) <= set(surface_order):
        raise CreditAnalysisError(f"{label} contains an unknown surface")
    return [surface for surface in surface_order if surface in set(surfaces)]


def _holistic_luna_schema(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    surface_values = list(state["manifest"]["surface_order"])
    candidate_pattern = rf"^{re.escape(str(state['analysis_id']))}\.c\.[0-9]{{6}}$"
    properties = {
        "schema": {"type": "string", "const": HOLISTIC_LUNA_RESULT_SCHEMA},
        "analysis_id": {"type": "string", "const": state["analysis_id"]},
        "task_id": {"type": "string", "const": task["task_id"]},
        "input_sha256": {"type": "string", "const": input_sha256},
        "coverage": {
            "type": "object",
            "properties": {
                "candidate_count": {"type": "integer", "const": len(task["candidate_ids"])},
                "candidate_ids_sha256": {
                    "type": "string",
                    "const": task["candidate_ids_sha256"],
                },
                "first_candidate_id": {
                    "type": "string",
                    "const": task["candidate_ids"][0],
                },
                "last_candidate_id": {
                    "type": "string",
                    "const": task["candidate_ids"][-1],
                },
            },
            "required": [
                "candidate_count",
                "candidate_ids_sha256",
                "first_candidate_id",
                "last_candidate_id",
            ],
            "additionalProperties": False,
        },
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9._-]*$"},
                    "kind": {"type": "string", "enum": contract["luna_candidate_kinds"]},
                    "title": {"type": "string", "minLength": 1},
                    "hypothesis": {"type": "string", "minLength": 1},
                    "surface_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "enum": surface_values},
                    },
                    "candidate_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "pattern": candidate_pattern},
                    },
                    "evidence_refs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "string",
                            "pattern": r"^(?:evidence|analysis)://",
                        },
                    },
                    "producer_owner_hint": {"type": "string", "minLength": 1},
                },
                "required": [
                    "id",
                    "kind",
                    "title",
                    "hypothesis",
                    "surface_ids",
                    "candidate_ids",
                    "evidence_refs",
                    "producer_owner_hint",
                ],
                "additionalProperties": False,
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _holistic_sol_schema(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    contract: Mapping[str, Any],
    luna_candidate_ids: Sequence[str],
    alias_record: Mapping[str, Any],
) -> dict[str, Any]:
    def string(max_length: int) -> dict[str, Any]:
        return {"type": "string", "minLength": 1, "maxLength": max_length}

    def strings(max_length: int, *, nonempty: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "array",
            "items": string(max_length),
        }
        if nonempty:
            result["minItems"] = 1
        return result

    def aliases(values: Sequence[str], *, nonempty: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "array",
            "items": {"type": "string", "enum": list(values)},
        }
        if nonempty:
            result["minItems"] = 1
        return result

    def number() -> dict[str, Any]:
        return {"type": "number", "minimum": 0}

    def boolean() -> dict[str, Any]:
        return {"type": "boolean"}

    def nullable_string(max_length: int) -> dict[str, Any]:
        return {"type": ["string", "null"], "maxLength": max_length}

    def closed(properties: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": dict(properties),
            "required": list(properties),
            "additionalProperties": False,
        }

    def objects(item: Mapping[str, Any]) -> dict[str, Any]:
        return {"type": "array", "items": dict(item)}

    del state, task, input_sha256
    canonical_to_alias, _ = _holistic_alias_lookups(alias_record)
    luna_aliases = [canonical_to_alias[item] for item in luna_candidate_ids]
    alias_tables = alias_record["aliases"]
    call_aliases = list(alias_tables["calls"])
    evidence_aliases = list(alias_tables["evidence"])
    recurrence = closed(
        {
            "calls_saved_per_affected_run": number(),
            "additional_recurring_calls_per_affected_run": number(),
            "affected_similar_run_frequency": number(),
            "affected_similar_run_frequency_range": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": number(),
            },
            "assumptions": strings(240, nonempty=True),
        }
    )
    cost = closed(
        {
            "estimated_model_calls": number(),
            "description": string(240),
        }
    )
    finding = closed(
        {
            "id": string(96),
            "title": string(160),
            "problem_summary": string(600),
            "waste_kind": {"type": "string", "enum": contract["waste_kinds"]},
            "affected_call_ids": aliases(call_aliases, nonempty=True),
            "evidence_refs": aliases(evidence_aliases, nonempty=True),
            "producer_type": {"type": "string", "enum": contract["producer_types"]},
            "producer_owner": string(240),
            "proposed_durable_control": string(600),
            "implementation_status": {
                "type": "string",
                "enum": contract["implementation_statuses"],
            },
            "targeted_verification": strings(320, nonempty=True),
            "recurrence": recurrence,
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "complexity": {"type": "string", "enum": contract["complexities"]},
            "one_time_implementation_cost": cost,
            "helper_categories": {
                "type": "array",
                "items": {"type": "string", "enum": contract["helper_categories"]},
            },
        }
    )
    risk = closed(
        {
            "id": string(96),
            "description": string(480),
            "affected_call_ids": aliases(call_aliases, nonempty=True),
            "evidence_refs": aliases(evidence_aliases, nonempty=True),
            "competing_explanations": strings(320, nonempty=True),
            "missing_fact": string(320),
            "verification_needed": strings(320, nonempty=True),
        }
    )
    temporary_review = closed(
        {
            "id": string(96),
            "source_luna_candidate_ids": aliases(luna_aliases, nonempty=True),
            "problem_solved": string(360),
            "affected_call_ids": aliases(call_aliases, nonempty=True),
            "observed_temporary_control": string(480),
            "final_canonical_evidence_refs": aliases(
                evidence_aliases,
                nonempty=True,
            ),
            "disposition": {
                "type": "string",
                "enum": contract["temporary_control_dispositions"],
            },
            "owning_producer": nullable_string(240),
            "recurrence_inputs": closed(
                {
                    "likely": boolean(),
                    "frequency_range": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": number(),
                    },
                    "basis": string(320),
                }
            ),
            "savings_inputs": closed(
                {
                    "expected_calls_saved": number(),
                    "maintenance_model_calls": number(),
                    "justifies_maintenance": boolean(),
                    "basis": string(320),
                }
            ),
            "finding_id": nullable_string(96),
            "no_finding_reason": nullable_string(360),
        }
    )
    properties = {
        "candidate_decisions": objects(
            closed(
                {
                    "luna_candidate_id": {
                        "type": "string",
                        "enum": luna_aliases,
                    },
                    "disposition": {
                        "type": "string",
                        "enum": contract["adjudication_dispositions"],
                    },
                    "reason": string(320),
                    "evidence_refs": aliases(evidence_aliases, nonempty=True),
                    "finding_ids": strings(96),
                    "risk_ids": strings(96),
                }
            )
        ),
        "confirmed_findings": objects(finding),
        "plausible_risks": objects(risk),
        "temporary_control_reviews": objects(temporary_review),
        "temporary_control_merges": objects(
            closed(
                {
                    "control_key": string(160),
                    "owning_producer": string(240),
                    "review_ids": strings(96, nonempty=True),
                    "finding_id": string(96),
                }
            )
        ),
        "helper_category_reviews": objects(
            closed(
                {
                    "category": {"type": "string", "enum": contract["helper_categories"]},
                    "applies": boolean(),
                    "evidence_refs": aliases(evidence_aliases),
                    "reason": string(320),
                }
            )
        ),
        "call_classifications": objects(
            closed(
                {
                    "call_ids": aliases(call_aliases, nonempty=True),
                    "classification": {
                        "type": "string",
                        "enum": contract["call_classifications"],
                    },
                    "reason_code": {
                        "type": ["string", "null"],
                        "enum": [*contract["necessary_reason_codes"], None],
                    },
                    "rationale": string(240),
                    "evidence_refs": aliases(evidence_aliases, nonempty=True),
                }
            )
        ),
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": HOLISTIC_SOL_TRANSPORT_SCHEMA,
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _validate_holistic_luna_result(
    raw: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    contract: Mapping[str, Any],
    compact: Mapping[str, Any],
) -> dict[str, Any]:
    _closed_result(
        raw,
        {"schema", "analysis_id", "task_id", "input_sha256", "coverage", "candidates"},
        "Luna discovery result",
    )
    if (
        raw.get("schema") != HOLISTIC_LUNA_RESULT_SCHEMA
        or raw.get("analysis_id") != state["analysis_id"]
        or raw.get("task_id") != task["task_id"]
        or raw.get("input_sha256") != input_sha256
    ):
        raise CreditAnalysisError("Luna discovery identity changed")
    coverage = raw.get("coverage")
    if not isinstance(coverage, dict):
        raise CreditAnalysisError("Luna coverage attestation is invalid")
    _closed_result(
        coverage,
        {"candidate_count", "candidate_ids_sha256", "first_candidate_id", "last_candidate_id"},
        "Luna coverage attestation",
    )
    expected_coverage = {
        "candidate_count": len(task["candidate_ids"]),
        "candidate_ids_sha256": task["candidate_ids_sha256"],
        "first_candidate_id": task["candidate_ids"][0],
        "last_candidate_id": task["candidate_ids"][-1],
    }
    if coverage != expected_coverage:
        raise CreditAnalysisError("Luna coverage attestation changed")
    candidates = _result_objects(raw.get("candidates"), "Luna candidates")
    allowed_candidates = set(task["candidate_ids"])
    record_index = {record["candidate_id"]: record for record in compact["records"]}
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, candidate in enumerate(candidates, start=1):
        label = f"Luna candidate {index}"
        _closed_result(
            candidate,
            {
                "id",
                "kind",
                "title",
                "hypothesis",
                "surface_ids",
                "candidate_ids",
                "evidence_refs",
                "producer_owner_hint",
            },
            label,
        )
        candidate_id = _identifier(candidate.get("id"), f"{label} ID")
        if candidate_id in seen_ids:
            raise CreditAnalysisError("Luna candidate ID is duplicated")
        seen_ids.add(candidate_id)
        if candidate.get("kind") not in contract["luna_candidate_kinds"]:
            raise CreditAnalysisError(f"{label} kind is invalid")
        surface_ids = _holistic_surface_ids(
            candidate.get("surface_ids"),
            f"{label} surfaces",
            state["manifest"]["surface_order"],
        )
        referenced = _result_deduped_strings(candidate.get("candidate_ids"), f"{label} calls")
        if not set(referenced) <= allowed_candidates:
            raise CreditAnalysisError(f"{label} references another Luna packet")
        raw_refs = _result_deduped_strings(
            candidate.get("evidence_refs"), f"{label} evidence"
        )
        # Older frozen prompts told Luna to include adjacent candidate IDs in
        # evidence_refs. Recover those packet-local IDs into their canonical
        # field while continuing to reject every other non-evidence value.
        candidate_refs = [ref for ref in raw_refs if ref in allowed_candidates]
        refs = _holistic_result_refs(
            [ref for ref in raw_refs if ref not in allowed_candidates],
            f"{label} evidence",
        )
        packet_refs = {
            ref
            for candidate_key in task["candidate_ids"]
            for ref in record_index[candidate_key]["evidence_refs"]
        }
        allowed_refs = set(packet_refs)
        allowed_refs.update(
            ref
            for record in compact["canonical_state"]
            if isinstance((ref := record.get("evidence_ref")), str)
        )
        allowed_refs.update(
            item["evidence_ref"] for item in compact["analysis_generated_activity"]
        )
        if not set(refs) <= allowed_refs:
            raise CreditAnalysisError(f"{label} cites evidence outside its Luna packet")
        # A causal hypothesis may cite an adjacent call from the same frozen
        # packet. Expand its mapping deterministically so Sol receives the
        # cited original record instead of only Luna's summary.
        referenced_set = set(referenced)
        referenced_set.update(candidate_refs)
        referenced_set.update(
            candidate_key
            for candidate_key in task["candidate_ids"]
            if set(record_index[candidate_key]["evidence_refs"]) & set(refs)
        )
        referenced = [
            candidate_key
            for candidate_key in task["candidate_ids"]
            if candidate_key in referenced_set
        ]
        for text_key in ("title", "hypothesis", "producer_owner_hint"):
            if not isinstance(candidate.get(text_key), str) or not candidate[text_key].strip():
                raise CreditAnalysisError(f"{label} {text_key} is empty")
        normalized.append({**candidate, "surface_ids": surface_ids, "candidate_ids": referenced, "evidence_refs": refs})
    return {
        "schema": HOLISTIC_LUNA_RESULT_SCHEMA,
        "analysis_id": state["analysis_id"],
        "task_id": task["task_id"],
        "input_sha256": input_sha256,
        "coverage": expected_coverage,
        "candidates": normalized,
    }


def _holistic_luna_results(
    state: Mapping[str, Any], manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for task in manifest["luna_tasks"]:
        result_record = state["execution"][task["task_id"]]["result"]
        if not isinstance(result_record, Mapping):
            raise CreditAnalysisError("Sol cannot start before all Luna results")
        results.append(_read_json(pathlib.Path(result_record["path"]), "accepted Luna result"))
    return results


def _holistic_sol_luna_results(
    state: Mapping[str, Any],
    compact: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Replace model-selected Luna IDs with stable collision-free controller IDs."""

    reserved = {
        str(identity)
        for record in compact["records"]
        for identity in (record["candidate_id"], record["call_id"])
    }
    reserved.update(_holistic_evidence_references(compact))
    normalized_results: list[dict[str, Any]] = []
    identity_index = 0
    for result in _holistic_luna_results(state, state["manifest"]):
        candidates: list[dict[str, Any]] = []
        for candidate in result["candidates"]:
            while True:
                identity_index += 1
                candidate_id = (
                    f"luna.{state['analysis_id']}.{identity_index:06d}"
                )
                if candidate_id not in reserved:
                    break
            reserved.add(candidate_id)
            candidates.append({**candidate, "id": candidate_id})
        normalized_results.append({**result, "candidates": candidates})
    return normalized_results


SOL_ALIAS_SCHEMA = "ceratops-credit-analysis-sol-alias-map.v1"


def _holistic_evidence_references(value: Any) -> list[str]:
    """Collect model-addressable evidence references in deterministic order."""

    references: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str) and item.startswith(("evidence://", "analysis://")):
            references.append(item)

    visit(value)
    return list(dict.fromkeys(references))


def _holistic_alias_table(values: Sequence[str], prefix: str) -> dict[str, str]:
    """Map short packet-local identifiers to canonical controller identifiers."""

    ordered = list(dict.fromkeys(str(value) for value in values))
    width = max(4, len(str(len(ordered))))
    return {
        f"{prefix}{index:0{width}d}": canonical
        for index, canonical in enumerate(ordered, start=1)
    }


def _holistic_sol_aliases(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    compact: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the private reversible alias map; this file is never model input."""

    evidence_refs = _holistic_evidence_references([compact, candidates])
    return {
        "schema": SOL_ALIAS_SCHEMA,
        "analysis_id": state["analysis_id"],
        "task_id": task["task_id"],
        "input_sha256": None,
        "aliases": {
            "records": _holistic_alias_table(
                [str(record["candidate_id"]) for record in compact["records"]],
                "p",
            ),
            "calls": _holistic_alias_table(
                [str(record["call_id"]) for record in compact["records"]],
                "c",
            ),
            "luna_candidates": _holistic_alias_table(
                [str(candidate["id"]) for candidate in candidates],
                "l",
            ),
            "evidence": _holistic_alias_table(evidence_refs, "e"),
        },
    }


def _holistic_alias_lookups(
    alias_record: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    aliases = alias_record.get("aliases")
    if not isinstance(aliases, Mapping) or set(aliases) != {
        "records",
        "calls",
        "luna_candidates",
        "evidence",
    }:
        raise CreditAnalysisError("Sol alias map is invalid")
    alias_to_canonical: dict[str, str] = {}
    for category in ("records", "calls", "luna_candidates", "evidence"):
        table = aliases.get(category)
        if not isinstance(table, Mapping):
            raise CreditAnalysisError("Sol alias table is invalid")
        for alias, canonical in table.items():
            if (
                not isinstance(alias, str)
                or not isinstance(canonical, str)
                or not alias
                or not canonical
                or alias in alias_to_canonical
            ):
                raise CreditAnalysisError("Sol alias identity is invalid")
            alias_to_canonical[alias] = canonical
    if len(set(alias_to_canonical.values())) != len(alias_to_canonical):
        raise CreditAnalysisError("Sol canonical identity is aliased twice")
    return (
        {canonical: alias for alias, canonical in alias_to_canonical.items()},
        alias_to_canonical,
    )


def _holistic_alias_value(value: Any, replacements: Mapping[str, str]) -> Any:
    """Replace canonical identifiers throughout one private model packet."""

    if isinstance(value, Mapping):
        return {
            str(key): _holistic_alias_value(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_holistic_alias_value(item, replacements) for item in value]
    if not isinstance(value, str):
        return value
    if value in replacements:
        return replacements[value]
    result = value
    for canonical in sorted(replacements, key=len, reverse=True):
        if canonical in result:
            result = result.replace(canonical, replacements[canonical])
    return result


def _holistic_read_sol_aliases(
    task: Mapping[str, Any], input_sha256: str
) -> dict[str, Any]:
    path = pathlib.Path(str(task["artifacts"]["aliases"]))
    aliases = _read_json(path, "Sol alias map")
    if (
        aliases.get("schema") != SOL_ALIAS_SCHEMA
        or aliases.get("task_id") != task["task_id"]
        or aliases.get("input_sha256") != input_sha256
    ):
        raise CreditAnalysisError("Sol alias map identity changed")
    _holistic_alias_lookups(aliases)
    return aliases


def _holistic_sol_input(
    *,
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
    compact: Mapping[str, Any],
    task: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    luna_results = _holistic_sol_luna_results(state, compact)
    candidates: list[dict[str, Any]] = []
    for result in luna_results:
        for candidate in result["candidates"]:
            candidates.append({**candidate, "source_task_id": result["task_id"]})
    record_index = {record["candidate_id"]: record for record in compact["records"]}
    per_candidate_limit = int(contract["chunking"]["sol_evidence_chars_per_candidate"])
    candidate_evidence = [
        {
            "luna_candidate_id": candidate["id"],
            "candidate_ids": candidate["candidate_ids"],
            "original_evidence": _holistic_projection(
                [record_index[candidate_id] for candidate_id in candidate["candidate_ids"]],
                limit=per_candidate_limit,
                surface_ids=candidate["surface_ids"],
            ),
        }
        for candidate in candidates
    ]
    surfaced_ids = {
        candidate_id for candidate in candidates for candidate_id in candidate["candidate_ids"]
    }
    high_signal = [
        {
            "candidate_id": record["candidate_id"],
            "call_id": record["call_id"],
            "workstream": record["workstream"],
            "surface_lenses": record["surface_lenses"],
            "reasons": record["high_signal_reasons"],
            "evidence_refs": record["evidence_refs"],
            "evidence": _holistic_projection(
                record,
                limit=min(1_500, per_candidate_limit),
                surface_ids=record["surface_lenses"],
            ),
        }
        for record in compact["records"]
        if record["high_signal_reasons"] and record["candidate_id"] not in surfaced_ids
    ]
    inventory = [
        [
            record["candidate_id"],
            record["call_id"],
            record["workstream"],
            record["surface_lenses"],
            record["high_signal_reasons"],
            record["volume"],
            record["evidence_refs"][0],
        ]
        for record in compact["records"]
    ]
    canonical_payload = {
        "schema": HOLISTIC_TASK_SCHEMA,
        "analysis_id": state["analysis_id"],
        "task_id": task["task_id"],
        "phase": "sol-adjudication",
        "surface_order": state["manifest"]["surface_order"],
        "analysis_policy": compact["analysis_policy"],
        "surface_contracts": {
            surface: _surface_reference_text(surface, contract)
            for surface in state["manifest"]["surface_order"]
        },
        "luna_results": luna_results,
        "luna_candidate_ids": [candidate["id"] for candidate in candidates],
        "candidate_original_evidence": candidate_evidence,
        "unsurfaced_high_signal_evidence": high_signal,
        "call_inventory": {
            "fields": [
                "candidate_id",
                "call_id",
                "workstream",
                "surface_lenses",
                "high_signal_reasons",
                "volume",
                "primary_evidence_ref",
            ],
            "rows": inventory,
        },
        "analysis_generated_activity": compact["analysis_generated_activity"],
        "canonical_state": compact["canonical_state"],
        "deterministic_totals": evidence["totals"],
        "pricing": evidence["pricing"],
        "helper_categories": contract["helper_categories"],
        "temporary_control_dispositions": contract["temporary_control_dispositions"],
        "call_classifications": contract["call_classifications"],
        "necessary_reason_codes": contract["necessary_reason_codes"],
        "maximum_unassessed_fraction": contract["coverage"]["maximum_unassessed_fraction"],
    }
    aliases = _holistic_sol_aliases(
        state=state,
        task=task,
        candidates=candidates,
        compact=compact,
    )
    canonical_to_alias, _ = _holistic_alias_lookups(aliases)
    payload = _holistic_alias_value(canonical_payload, canonical_to_alias)
    budget_chars = int(state["model_specs"]["sol"]["evidence_char_budget"])
    if _json_chars(payload) > budget_chars:
        payload["unsurfaced_high_signal_evidence"] = _holistic_alias_value(
            [
                {
                    key: item[key]
                    for key in (
                        "candidate_id",
                        "call_id",
                        "workstream",
                        "surface_lenses",
                        "reasons",
                        "evidence_refs",
                    )
                }
                for item in high_signal
            ],
            canonical_to_alias,
        )
    if _json_chars(payload) > budget_chars:
        payload["candidate_original_evidence"] = _holistic_alias_value(
            [
                {
                    "luna_candidate_id": item["luna_candidate_id"],
                    "candidate_ids": item["candidate_ids"],
                    "original_evidence": _holistic_projection(
                        [
                            record_index[candidate_id]
                            for candidate_id in item["candidate_ids"]
                        ],
                        limit=1_500,
                        surface_ids=next(
                            candidate["surface_ids"]
                            for candidate in candidates
                            if candidate["id"] == item["luna_candidate_id"]
                        ),
                    ),
                }
                for item in candidate_evidence
            ],
            canonical_to_alias,
        )
    if _json_chars(payload) > budget_chars:
        raise CreditAnalysisError(
            "single Sol adjudication packet exceeds the dynamic context budget"
        )
    return payload, [str(candidate["id"]) for candidate in candidates], aliases


def _holistic_prepare_task(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    contract: Mapping[str, Any],
    compact: Mapping[str, Any],
    task: Mapping[str, Any],
) -> tuple[dict[str, Any], str, pathlib.Path, pathlib.Path, list[str]]:
    input_path = pathlib.Path(str(task["artifacts"]["input"]))
    if task["phase"] == "luna-discovery":
        payload = _read_json(input_path, "Luna input")
        digest = _file_hash(input_path)
        if digest != task["input_sha256"]:
            raise CreditAnalysisError("Luna input changed")
        luna_candidate_ids: list[str] = []
        alias_record: dict[str, Any] | None = None
    else:
        payload, luna_candidate_ids, alias_record = _holistic_sol_input(
            state=state,
            evidence=evidence,
            contract=contract,
            compact=compact,
            task=task,
        )
        digest = _write_or_verify_task_input(input_path, payload)
        alias_record = {**alias_record, "input_sha256": digest}
        _write_or_verify_json(
            pathlib.Path(str(task["artifacts"]["aliases"])),
            alias_record,
            "Sol alias map",
        )
    schema_path = pathlib.Path(str(task["artifacts"]["schema"]))
    prompt_path = pathlib.Path(str(task["artifacts"]["prompt"]))
    existing_contract = schema_path.exists() or prompt_path.exists()
    if existing_contract:
        if (
            not schema_path.is_file()
            or schema_path.is_symlink()
            or not prompt_path.is_file()
            or prompt_path.is_symlink()
        ):
            raise CreditAnalysisError("frozen model prompt/schema pair is incomplete")
        schema = _read_json(schema_path, "frozen holistic output schema")
        prompt_text = prompt_path.read_text(encoding="utf-8")
        properties = schema.get("properties")
        input_identity = (
            properties.get("input_sha256")
            if isinstance(properties, Mapping)
            else None
        )
        luna_contract_valid = (
            task["phase"] == "luna-discovery"
            and isinstance(input_identity, Mapping)
            and input_identity.get("const") == digest
        )
        sol_contract_valid = (
            task["phase"] == "sol-adjudication"
            and schema.get("title") == HOLISTIC_SOL_TRANSPORT_SCHEMA
        )
        if (
            not (luna_contract_valid or sol_contract_valid)
            or f"The input identity is {digest}." not in prompt_text
        ):
            raise CreditAnalysisError("frozen model prompt/schema identity changed")
    else:
        if task["phase"] == "luna-discovery":
            schema = _holistic_luna_schema(
                state=state,
                task=task,
                input_sha256=digest,
                contract=contract,
            )
        else:
            if alias_record is None:
                raise CreditAnalysisError("Sol alias map was not prepared")
            schema = _holistic_sol_schema(
                state=state,
                task=task,
                input_sha256=digest,
                contract=contract,
                luna_candidate_ids=luna_candidate_ids,
                alias_record=alias_record,
            )
        _write_or_verify_json(schema_path, schema, "holistic output schema")
        prompt = _holistic_prompt(
            state=state,
            task=task,
            input_payload=payload,
            input_sha256=digest,
            luna_candidate_ids=luna_candidate_ids,
        )
        _write_or_verify_text(prompt_path, prompt, "holistic model prompt")
    return payload, digest, prompt_path, schema_path, luna_candidate_ids


def _holistic_prompt(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_payload: Mapping[str, Any],
    input_sha256: str,
    luna_candidate_ids: Sequence[str],
) -> str:
    lineage = json.dumps(
        {
            "controller_analysis_id": state["analysis_id"],
            "task_id": task["task_id"],
            "ephemeral_child": True,
            "source_cutoff_precedes_this_child": True,
        },
        separators=(",", ":"),
    )
    common = f"""Controller lineage: {lineage}
This is an analysis-only child. Do not use tools, read files, run commands, or
modify any repository, skill, prompt, helper, workflow, or instruction. Analyze
only the supplied packet and return one JSON object matching the output schema.
Apply the supplied analysis_policy exactly. Intentional full skill-body injection
is required runtime context, never credit waste. Never recommend a reasoning
setting, effort, or level. Use only frozen local and canonical-state evidence;
when broader or deep research would be required, preserve the uncertainty and
provide a concise paste-ready targeted official-source check instead of guessing.
The input identity is {input_sha256}.
"""
    if task["phase"] == "luna-discovery":
        instructions = """
Act as the high-recall discovery tier. The packet contains every selected call
assigned to it in causal order and exposes the supplied fixed lenses in order.
Inspect all calls. Emit only plausible findings and plausible risks, plus every
observed temporary control for mandatory Sol review even when it appears
intentional or harmless. Do not enumerate routine dismissals,
do not classify every action or call-surface pair, do not calculate savings, and
do not make final findings. Every emitted candidate must cite supplied candidate
IDs and packet-local original evidence references. Put candidate IDs only in
`candidate_ids`; put only `evidence://` or `analysis://` values in
`evidence_refs`. When citing an adjacent record, add its candidate ID to
`candidate_ids` and its original reference to `evidence_refs`. Keep shared producer/control episodes
together and keep analysis-overhead work separate from producer work. Aim for
about 2,500 output tokens; concise hypotheses are sufficient and genuine
candidates must not be silently dropped.
"""
    else:
        instructions = f"""
Act as the sole final adjudication and synthesis tier. Adjudicate every Luna
candidate exactly once ({len(luna_candidate_ids)} total) against its original
evidence excerpt. Review every supplied surface section in its fixed order,
merge overlapping findings once by owning producer/control, and preserve every
confirmed finding. Perform the mandatory temporary-control review for every
temporary-control candidate, using exactly one allowed disposition; transient
work is not automatically defective, and a permanent recommendation requires
likely recurrence plus positive maintenance-adjusted savings. Review a
temporary control recognized during adjudication even if Luna gave it another
candidate kind. Only `durable-control-missing` with the recurrence and savings
gate satisfied may link to a finding; every other disposition needs an explicit
no-finding reason.

Classify every source call exactly once in compact groups; group order and
contiguity are transport-only and the controller canonicalizes source order and
derives workstreams. Use only the packet-local call, Luna-candidate, and evidence
aliases exposed in the packet and output schema; do not reproduce canonical IDs.
Keep analysis-overhead findings separate from producer findings and savings.
Use `necessary` only for a specific active gate with a supplied reason code;
never use it as a catch-all. Use `reviewed_no_confirmed_waste` for inspected calls
without confirmed waste. `unassessed` is only for a decision-blocking evidence
gap and must stay within the supplied cap. Let explicit avoidable call
classifications govern model-call finding membership and observed counts; an
unimplemented finding may include already-implemented calls when at least one
affected call remains unimplemented. Before labeling a durable control missing,
check the frozen current canonical state for the relevant instruction, skill,
automation, or helper contract. If that state proves the safeguard already
exists, preserve `implementation_status` as `implemented` and describe violating
behavior as a compliance or runtime gap; do not propose a duplicate control. Do
not perform broad rediscovery that duplicates Luna, but use the supplied
high-signal audit evidence to catch a material miss. Return only the semantic
fields in the schema: do not restate identity, surface summaries, workstreams,
observed counts, recurrence arithmetic, or an analysis summary. Keep rationales
compact and do not repeat evidence text already addressed by an evidence alias.
Aim for about 1,500 visible output tokens while retaining every candidate
decision, confirmed finding, material variant, required review, and call
classification.
"""
    packet = json.dumps(input_payload, ensure_ascii=False, separators=(",", ":"))
    return common + instructions + "\nInput packet:\n" + packet + "\n"


def _holistic_workstream_by_call(compact: Mapping[str, Any]) -> dict[str, str]:
    return {str(record["call_id"]): str(record["workstream"]) for record in compact["records"]}


def _validate_holistic_finding(
    finding: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    call_order: Sequence[str],
    workstreams: Mapping[str, str],
    surface_order: Sequence[str],
    label: str,
) -> dict[str, Any]:
    fields = {
        "id",
        "title",
        "problem_summary",
        "waste_kind",
        "affected_call_ids",
        "evidence_refs",
        "evidence_narrative",
        "producer_type",
        "producer_owner",
        "workstream",
        "proposed_durable_control",
        "implementation_status",
        "targeted_verification",
        "observed_avoidable_call_count",
        "recurrence",
        "confidence",
        "complexity",
        "one_time_implementation_cost",
        "helper_categories",
        "contributing_surfaces",
    }
    _closed_result(finding, fields, label)
    _identifier(finding.get("id"), f"{label} ID")
    for key in (
        "title",
        "problem_summary",
        "evidence_narrative",
        "producer_owner",
        "proposed_durable_control",
    ):
        if not isinstance(finding.get(key), str) or not finding[key].strip():
            raise CreditAnalysisError(f"{label} {key} is empty")
    if finding.get("waste_kind") not in contract["waste_kinds"]:
        raise CreditAnalysisError(f"{label} waste kind is invalid")
    calls = _result_deduped_strings(finding.get("affected_call_ids"), f"{label} calls")
    if not set(calls) <= set(call_order):
        raise CreditAnalysisError(f"{label} references an unknown call")
    expected_order = [call_id for call_id in call_order if call_id in set(calls)]
    if calls != expected_order:
        raise CreditAnalysisError(f"{label} calls are reordered")
    if finding.get("workstream") not in {"producer", "analysis-overhead"}:
        raise CreditAnalysisError(f"{label} workstream is invalid")
    observed_workstreams = {workstreams[call_id] for call_id in calls}
    if len(observed_workstreams) != 1:
        raise CreditAnalysisError(f"{label} mixes producer and analysis work")
    workstream = next(iter(observed_workstreams))
    refs = _holistic_result_refs(finding.get("evidence_refs"), f"{label} evidence")
    if finding.get("producer_type") not in contract["producer_types"]:
        raise CreditAnalysisError(f"{label} producer type is invalid")
    if finding.get("implementation_status") not in contract["implementation_statuses"]:
        raise CreditAnalysisError(f"{label} implementation status is invalid")
    verification = _result_deduped_strings(
        finding.get("targeted_verification"), f"{label} verification"
    )
    observed = finding.get("observed_avoidable_call_count")
    if not isinstance(observed, int) or isinstance(observed, bool) or observed < 0:
        raise CreditAnalysisError(f"{label} observed call count is invalid")
    if finding["waste_kind"] == "context-volume" and observed != 0:
        raise CreditAnalysisError(f"{label} volume-only finding saves model calls")
    recurrence = _validate_recurrence_inputs(finding.get("recurrence"), f"{label} recurrence")
    net = recurrence["calls_saved_per_affected_run"] - recurrence[
        "additional_recurring_calls_per_affected_run"
    ]
    expected_savings = net * recurrence["affected_similar_run_frequency"]
    if not math.isclose(
        recurrence["estimated_calls_saved_per_similar_run"],
        expected_savings,
        rel_tol=1e-6,
        abs_tol=1e-6,
    ):
        raise CreditAnalysisError(f"{label} recurrence arithmetic is invalid")
    if finding["waste_kind"] == "model-calls" and expected_savings <= 0:
        raise CreditAnalysisError(f"{label} has non-positive recurring savings")
    confidence = finding.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise CreditAnalysisError(f"{label} confidence is invalid")
    if finding.get("complexity") not in contract["complexities"]:
        raise CreditAnalysisError(f"{label} complexity is invalid")
    cost = finding.get("one_time_implementation_cost")
    if not isinstance(cost, dict):
        raise CreditAnalysisError(f"{label} implementation cost is invalid")
    _closed_result(cost, {"estimated_model_calls", "description"}, f"{label} implementation cost")
    _number(cost.get("estimated_model_calls"), f"{label} implementation calls")
    if not isinstance(cost.get("description"), str) or not cost["description"].strip():
        raise CreditAnalysisError(f"{label} implementation description is empty")
    categories = _result_deduped_strings(
        finding.get("helper_categories"), f"{label} helper categories", empty=True
    )
    if not set(categories) <= set(contract["helper_categories"]):
        raise CreditAnalysisError(f"{label} helper category is invalid")
    surfaces = _holistic_surface_ids(
        finding.get("contributing_surfaces"),
        f"{label} surfaces",
        surface_order,
    )
    return {
        **finding,
        "affected_call_ids": calls,
        "evidence_refs": refs,
        "workstream": workstream,
        "targeted_verification": verification,
        "recurrence": recurrence,
        "helper_categories": categories,
        "contributing_surfaces": surfaces,
    }


def _holistic_call_classifications(
    value: Any,
    *,
    contract: Mapping[str, Any],
    call_order: Sequence[str],
    workstreams: Mapping[str, str],
) -> tuple[list[dict[str, Any]], dict[str, str], int]:
    """Validate model judgments and normalize their grouping to source order.

    Group boundaries are only a compact transport detail. The semantic fields
    remain model-owned while deterministic code splits or rejoins adjacent
    calls so every frozen call appears exactly once in causal order.
    """

    by_call: dict[str, dict[str, Any]] = {}
    for index, group in enumerate(
        _result_objects(value, "call classifications"), start=1
    ):
        label = f"call classification group {index}"
        _closed_result(
            group,
            {
                "call_ids",
                "classification",
                "reason_code",
                "rationale",
                "evidence_refs",
                "workstream",
            },
            label,
        )
        calls = _result_deduped_strings(group.get("call_ids"), f"{label} calls")
        unknown = set(calls) - set(call_order)
        if unknown:
            raise CreditAnalysisError(f"{label} references an unknown call")
        classification = str(group.get("classification"))
        if classification not in contract["call_classifications"]:
            raise CreditAnalysisError(f"{label} classification is invalid")
        reason = group.get("reason_code")
        if classification == "necessary":
            if reason not in contract["necessary_reason_codes"]:
                raise CreditAnalysisError(f"{label} necessary reason is invalid")
        elif reason is not None:
            raise CreditAnalysisError(f"{label} non-necessary reason must be null")
        if group.get("workstream") not in {"producer", "analysis-overhead"}:
            raise CreditAnalysisError(f"{label} workstream is invalid")
        refs = _holistic_result_refs(group.get("evidence_refs"), f"{label} evidence")
        if not isinstance(group.get("rationale"), str) or not group["rationale"].strip():
            raise CreditAnalysisError(f"{label} rationale is empty")
        for call_id in calls:
            if call_id in by_call:
                raise CreditAnalysisError(
                    f"call classification is duplicated: {call_id}"
                )
            # Grouping is model transport; the frozen call inventory remains the
            # authority for workstream identity and deterministic split points.
            by_call[call_id] = {
                "classification": classification,
                "reason_code": reason,
                "rationale": group["rationale"],
                "evidence_refs": refs,
                "workstream": workstreams[call_id],
            }
    if set(by_call) != set(call_order):
        raise CreditAnalysisError("call classifications are missing or cross-analysis")

    normalized: list[dict[str, Any]] = []
    for call_id in call_order:
        detail = by_call[call_id]
        if normalized and all(
            normalized[-1][key] == detail[key]
            for key in (
                "classification",
                "reason_code",
                "rationale",
                "evidence_refs",
                "workstream",
            )
        ):
            normalized[-1]["call_ids"].append(call_id)
        else:
            normalized.append({"call_ids": [call_id], **detail})
    classification_by_call = {
        call_id: str(detail["classification"]) for call_id, detail in by_call.items()
    }
    unassessed = sum(
        classification == "unassessed"
        for classification in classification_by_call.values()
    )
    return normalized, classification_by_call, unassessed


def _holistic_reconcile_findings(
    findings: Sequence[dict[str, Any]],
    classification_by_call: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Resolve finding membership from Sol's explicit per-call judgments."""

    avoidable = {"avoidable_implemented", "avoidable_unimplemented"}
    normalized: list[dict[str, Any]] = []
    for finding in findings:
        if finding["waste_kind"] != "model-calls":
            normalized.append(finding)
            continue
        calls = [
            call_id
            for call_id in finding["affected_call_ids"]
            if classification_by_call[call_id] in avoidable
        ]
        if not calls:
            raise CreditAnalysisError("model-call finding has no avoidable call evidence")
        if finding["observed_avoidable_call_count"] != len(calls):
            raise CreditAnalysisError("finding count conflicts with explicit call accounting")
        classifications = {classification_by_call[call_id] for call_id in calls}
        if finding["implementation_status"] == "implemented":
            if classifications != {"avoidable_implemented"}:
                raise CreditAnalysisError(
                    "implemented finding conflicts with explicit call accounting"
                )
        elif "avoidable_unimplemented" not in classifications:
            raise CreditAnalysisError(
                "unimplemented finding has no unimplemented avoidable call"
            )
        normalized.append(
            {
                **finding,
                "affected_call_ids": calls,
                "observed_avoidable_call_count": len(calls),
            }
        )
    return normalized


def _holistic_reconcile_orphaned_avoidable_calls(
    classifications: Sequence[dict[str, Any]],
    findings: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str], int]:
    """Conservatively unassess avoidability that has no model-call finding.

    The controller never invents a finding or savings claim. The caller's
    existing unassessed-coverage gate still rejects broad inconsistencies.
    """

    finding_calls = {
        call_id
        for finding in findings
        if finding["waste_kind"] == "model-calls"
        for call_id in finding["affected_call_ids"]
    }
    normalized: list[dict[str, Any]] = []
    for group in classifications:
        for call_id in group["call_ids"]:
            detail = {
                key: value
                for key, value in group.items()
                if key != "call_ids"
            }
            if (
                detail["classification"]
                in {"avoidable_implemented", "avoidable_unimplemented"}
                and call_id not in finding_calls
            ):
                detail.update(
                    {
                        "classification": "unassessed",
                        "reason_code": None,
                        "rationale": (
                            "Sol marked this call avoidable but supplied no "
                            "model-call finding; the controller conservatively "
                            "left it unassessed."
                        ),
                    }
                )
            if normalized and all(
                normalized[-1][key] == detail[key] for key in detail
            ):
                normalized[-1]["call_ids"].append(call_id)
            else:
                normalized.append({"call_ids": [call_id], **detail})
    classification_by_call = {
        call_id: str(group["classification"])
        for group in normalized
        for call_id in group["call_ids"]
    }
    unassessed = sum(
        classification == "unassessed"
        for classification in classification_by_call.values()
    )
    return normalized, classification_by_call, unassessed


def _validate_holistic_sol_result(
    raw: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    contract: Mapping[str, Any],
    compact: Mapping[str, Any],
    luna_candidate_ids: Sequence[str],
) -> dict[str, Any]:
    fields = {
        "schema",
        "analysis_id",
        "task_id",
        "input_sha256",
        "surface_summaries",
        "candidate_decisions",
        "confirmed_findings",
        "plausible_risks",
        "temporary_control_reviews",
        "temporary_control_merges",
        "helper_category_reviews",
        "call_classifications",
        "analysis_summary",
    }
    _closed_result(raw, fields, "Sol adjudication result")
    if (
        raw.get("schema") != HOLISTIC_SOL_RESULT_SCHEMA
        or raw.get("analysis_id") != state["analysis_id"]
        or raw.get("task_id") != task["task_id"]
        or raw.get("input_sha256") != input_sha256
    ):
        raise CreditAnalysisError("Sol adjudication identity changed")
    surface_order = list(state["manifest"]["surface_order"])
    call_order = list(state["manifest"]["call_ids"])
    workstreams = _holistic_workstream_by_call(compact)
    findings = [
        _validate_holistic_finding(
            finding,
            contract=contract,
            call_order=call_order,
            workstreams=workstreams,
            surface_order=surface_order,
            label=f"confirmed finding {index}",
        )
        for index, finding in enumerate(
            _result_objects(raw.get("confirmed_findings"), "confirmed findings"),
            start=1,
        )
    ]
    classifications, classification_by_call, unassessed = (
        _holistic_call_classifications(
            raw.get("call_classifications"),
            contract=contract,
            call_order=call_order,
            workstreams=workstreams,
        )
    )
    classifications, classification_by_call, unassessed = (
        _holistic_reconcile_orphaned_avoidable_calls(classifications, findings)
    )
    maximum_unassessed = math.floor(
        len(call_order) * float(contract["coverage"]["maximum_unassessed_fraction"])
    )
    if unassessed > maximum_unassessed:
        raise CreditAnalysisError(
            f"unassessed calls exceed the contract limit: {unassessed} > {maximum_unassessed}"
        )
    findings = _holistic_reconcile_findings(findings, classification_by_call)
    finding_by_id = {finding["id"]: finding for finding in findings}
    if len(finding_by_id) != len(findings):
        raise CreditAnalysisError("confirmed finding ID is duplicated")
    avoidable_calls = {
        call_id
        for call_id, classification in classification_by_call.items()
        if classification in {"avoidable_implemented", "avoidable_unimplemented"}
    }
    finding_calls = {
        call_id
        for finding in findings
        if finding["waste_kind"] == "model-calls"
        for call_id in finding["affected_call_ids"]
    }
    if avoidable_calls != finding_calls:
        raise CreditAnalysisError("avoidable call classifications do not match findings")
    risks: list[dict[str, Any]] = []
    for index, risk in enumerate(_result_objects(raw.get("plausible_risks"), "plausible risks"), start=1):
        label = f"plausible risk {index}"
        _closed_result(
            risk,
            {
                "id",
                "description",
                "affected_call_ids",
                "evidence_refs",
                "workstream",
                "contributing_surfaces",
                "competing_explanations",
                "missing_fact",
                "verification_needed",
            },
            label,
        )
        _identifier(risk.get("id"), f"{label} ID")
        calls = _result_deduped_strings(risk.get("affected_call_ids"), f"{label} calls")
        if calls != [call_id for call_id in call_order if call_id in set(calls)]:
            raise CreditAnalysisError(f"{label} calls are missing or reordered")
        if risk.get("workstream") not in {"producer", "analysis-overhead"}:
            raise CreditAnalysisError(f"{label} workstream is invalid")
        observed_workstreams = {workstreams.get(call_id) for call_id in calls}
        if None in observed_workstreams or len(observed_workstreams) != 1:
            raise CreditAnalysisError(f"{label} mixes producer and analysis work")
        workstream = next(iter(observed_workstreams))
        surfaces = _holistic_surface_ids(
            risk.get("contributing_surfaces"),
            f"{label} surfaces",
            surface_order,
        )
        normalized = {
            **risk,
            "affected_call_ids": calls,
            "evidence_refs": _holistic_result_refs(risk.get("evidence_refs"), f"{label} evidence"),
            "workstream": workstream,
            "contributing_surfaces": surfaces,
            "competing_explanations": _result_deduped_strings(
                risk.get("competing_explanations"), f"{label} explanations"
            ),
            "verification_needed": _result_deduped_strings(
                risk.get("verification_needed"), f"{label} verification"
            ),
        }
        for key in ("description", "missing_fact"):
            if not isinstance(normalized.get(key), str) or not normalized[key].strip():
                raise CreditAnalysisError(f"{label} {key} is empty")
        risks.append(normalized)
    risk_by_id = {risk["id"]: risk for risk in risks}
    if len(risk_by_id) != len(risks):
        raise CreditAnalysisError("plausible risk ID is duplicated")
    decisions = _result_objects(raw.get("candidate_decisions"), "candidate decisions")
    observed_candidate_ids: list[str] = []
    for index, decision in enumerate(decisions, start=1):
        label = f"candidate decision {index}"
        _closed_result(
            decision,
            {"luna_candidate_id", "disposition", "reason", "evidence_refs", "finding_ids", "risk_ids"},
            label,
        )
        candidate_id = decision.get("luna_candidate_id")
        if not isinstance(candidate_id, str):
            raise CreditAnalysisError(f"{label} candidate ID is invalid")
        observed_candidate_ids.append(candidate_id)
        disposition = decision.get("disposition")
        if disposition not in contract["adjudication_dispositions"]:
            raise CreditAnalysisError(f"{label} disposition is invalid")
        finding_ids = _result_deduped_strings(decision.get("finding_ids"), f"{label} findings", empty=True)
        risk_ids = _result_deduped_strings(decision.get("risk_ids"), f"{label} risks", empty=True)
        if not set(finding_ids) <= set(finding_by_id) or not set(risk_ids) <= set(risk_by_id):
            raise CreditAnalysisError(f"{label} references an unknown outcome")
        if disposition == "confirmed-finding" and (not finding_ids or risk_ids):
            raise CreditAnalysisError(f"{label} confirmed outcome is inconsistent")
        if disposition == "plausible-risk" and (not risk_ids or finding_ids):
            raise CreditAnalysisError(f"{label} risk outcome is inconsistent")
        if disposition == "dismissed-candidate" and (finding_ids or risk_ids):
            raise CreditAnalysisError(f"{label} dismissed outcome has an outcome ID")
        decision["finding_ids"] = finding_ids
        decision["risk_ids"] = risk_ids
        decision["evidence_refs"] = _holistic_result_refs(
            decision.get("evidence_refs"), f"{label} evidence"
        )
        if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
            raise CreditAnalysisError(f"{label} reason is empty")
    if observed_candidate_ids != list(luna_candidate_ids) or len(observed_candidate_ids) != len(set(observed_candidate_ids)):
        raise CreditAnalysisError("Sol did not adjudicate every Luna candidate exactly once")
    luna_results = _holistic_sol_luna_results(state, compact)
    all_luna_candidate_ids = [
        candidate["id"]
        for result in luna_results
        for candidate in result["candidates"]
    ]
    temporary_candidate_ids = [
        candidate["id"]
        for result in luna_results
        for candidate in result["candidates"]
        if candidate["kind"] == "temporary-control"
    ]
    reviews = _result_objects(raw.get("temporary_control_reviews"), "temporary-control reviews")
    review_by_id: dict[str, dict[str, Any]] = {}
    reviewed_temporary: list[str] = []
    for index, review in enumerate(reviews, start=1):
        label = f"temporary-control review {index}"
        _closed_result(
            review,
            {
                "id",
                "source_luna_candidate_ids",
                "problem_solved",
                "affected_call_ids",
                "observed_temporary_control",
                "final_canonical_evidence_refs",
                "disposition",
                "owning_producer",
                "recurrence_inputs",
                "savings_inputs",
                "finding_id",
                "no_finding_reason",
                "contributing_surfaces",
            },
            label,
        )
        review_id = _identifier(review.get("id"), f"{label} ID")
        if review_id in review_by_id:
            raise CreditAnalysisError("temporary-control review ID is duplicated")
        sources = _result_deduped_strings(
            review.get("source_luna_candidate_ids"), f"{label} Luna candidates"
        )
        if not set(sources) <= set(all_luna_candidate_ids):
            raise CreditAnalysisError(f"{label} references an unknown Luna candidate")
        reviewed_temporary.extend(sources)
        calls = _result_deduped_strings(review.get("affected_call_ids"), f"{label} calls")
        if calls != [call_id for call_id in call_order if call_id in set(calls)]:
            raise CreditAnalysisError(f"{label} calls are invalid")
        _holistic_result_refs(
            review.get("final_canonical_evidence_refs"), f"{label} canonical evidence"
        )
        disposition = review.get("disposition")
        if disposition not in contract["temporary_control_dispositions"]:
            raise CreditAnalysisError(f"{label} disposition is invalid")
        recurrence = review.get("recurrence_inputs")
        savings = review.get("savings_inputs")
        if not isinstance(recurrence, dict) or not isinstance(savings, dict):
            raise CreditAnalysisError(f"{label} recurrence or savings is invalid")
        _closed_result(recurrence, {"likely", "frequency_range", "basis"}, f"{label} recurrence")
        _closed_result(
            savings,
            {"expected_calls_saved", "maintenance_model_calls", "justifies_maintenance", "basis"},
            f"{label} savings",
        )
        frequency = recurrence.get("frequency_range")
        if (
            not isinstance(recurrence.get("likely"), bool)
            or not isinstance(frequency, list)
            or len(frequency) != 2
            or any(not isinstance(value, (int, float)) or value < 0 for value in frequency)
            or frequency[1] < frequency[0]
        ):
            raise CreditAnalysisError(f"{label} recurrence is invalid")
        expected_saved = _number(savings.get("expected_calls_saved"), f"{label} expected savings")
        maintenance = _number(savings.get("maintenance_model_calls"), f"{label} maintenance calls")
        if not isinstance(savings.get("justifies_maintenance"), bool):
            raise CreditAnalysisError(f"{label} savings gate is invalid")
        finding_id = review.get("finding_id")
        no_finding = review.get("no_finding_reason")
        nonfinding_dispositions = {
            "transient-by-design",
            "permanently-implemented",
            "run-only-useful",
        }
        if disposition in nonfinding_dispositions:
            finding_id = None
            if not isinstance(no_finding, str) or not no_finding.strip():
                no_finding = (
                    f"The {disposition} disposition does not represent a missing "
                    "durable control."
                )
        if finding_id is not None:
            if (
                not isinstance(finding_id, str)
                or finding_id not in finding_by_id
                or disposition != "durable-control-missing"
                or recurrence["likely"] is not True
                or savings["justifies_maintenance"] is not True
                or expected_saved <= maintenance
                or no_finding is not None
            ):
                raise CreditAnalysisError(f"{label} permanent recommendation fails ROI gating")
        elif not isinstance(no_finding, str) or not no_finding.strip():
            raise CreditAnalysisError(f"{label} needs an explicit no-finding reason")
        surfaces = _holistic_surface_ids(
            review.get("contributing_surfaces"),
            f"{label} surfaces",
            surface_order,
        )
        normalized_review = {
            **review,
            "source_luna_candidate_ids": sources,
            "affected_call_ids": calls,
            "finding_id": finding_id,
            "no_finding_reason": no_finding,
            "contributing_surfaces": surfaces,
        }
        review_by_id[review_id] = normalized_review
    if (
        len(reviewed_temporary) != len(set(reviewed_temporary))
        or not set(temporary_candidate_ids) <= set(reviewed_temporary)
    ):
        raise CreditAnalysisError(
            "temporary-control review coverage is missing or duplicated"
        )
    nonfinding_temporary_sources = {
        candidate_id
        for review in review_by_id.values()
        if review["finding_id"] is None
        for candidate_id in review["source_luna_candidate_ids"]
    }
    for decision in decisions:
        if (
            decision["luna_candidate_id"] in nonfinding_temporary_sources
            and decision["disposition"] == "confirmed-finding"
        ):
            implemented_finding_ids = [
                finding_id
                for finding_id in decision["finding_ids"]
                if finding_by_id[finding_id]["implementation_status"]
                == "implemented"
            ]
            if implemented_finding_ids:
                decision["finding_ids"] = implemented_finding_ids
            else:
                decision["disposition"] = "dismissed-candidate"
                decision["finding_ids"] = []
                decision["risk_ids"] = []
                decision["reason"] = (
                    "The mandatory temporary-control disposition records no "
                    "missing durable control."
                )
    referenced_findings = {
        finding_id for decision in decisions for finding_id in decision["finding_ids"]
    }
    referenced_risks = {
        risk_id for decision in decisions for risk_id in decision["risk_ids"]
    }
    if referenced_findings != set(finding_by_id) or referenced_risks != set(risk_by_id):
        raise CreditAnalysisError("Sol outcome is not linked to a Luna candidate")

    raw_merges = _result_objects(
        raw.get("temporary_control_merges"), "temporary-control merges"
    )
    merges: list[dict[str, Any]] = []
    merged_reviews: set[str] = set()
    merge_keys: set[tuple[str, str]] = set()
    for index, merge in enumerate(raw_merges, start=1):
        label = f"temporary-control merge {index}"
        _closed_result(
            merge,
            {"control_key", "owning_producer", "review_ids", "contributing_surfaces", "finding_id"},
            label,
        )
        merge_key = (
            str(merge.get("owning_producer")),
            str(merge.get("control_key")),
        )
        if merge_key in merge_keys:
            raise CreditAnalysisError("temporary-control owner/control is merged twice")
        merge_keys.add(merge_key)
        review_ids = _result_deduped_strings(merge.get("review_ids"), f"{label} reviews")
        if not set(review_ids) <= set(review_by_id):
            raise CreditAnalysisError(f"{label} review ownership is invalid")
        eligible_review_ids = [
            review_id
            for review_id in review_ids
            if review_by_id[review_id]["finding_id"] is not None
        ]
        _holistic_surface_ids(
            merge.get("contributing_surfaces"),
            f"{label} surfaces",
            surface_order,
        )
        if not eligible_review_ids:
            continue
        if set(eligible_review_ids) & merged_reviews:
            raise CreditAnalysisError(f"{label} review ownership is invalid")
        finding_id = merge.get("finding_id")
        if finding_id not in finding_by_id or any(
            review_by_id[review_id]["finding_id"] != finding_id
            for review_id in eligible_review_ids
        ):
            raise CreditAnalysisError(f"{label} finding ownership is invalid")
        merged_reviews.update(eligible_review_ids)
        surfaces = [
            surface
            for surface in surface_order
            if any(
                surface in review_by_id[review_id]["contributing_surfaces"]
                for review_id in eligible_review_ids
            )
        ]
        merges.append(
            {
                **merge,
                "review_ids": eligible_review_ids,
                "contributing_surfaces": surfaces,
            }
        )
    required_merged = {review_id for review_id, review in review_by_id.items() if review["finding_id"] is not None}
    if merged_reviews != required_merged:
        raise CreditAnalysisError("temporary-control confirmed findings were not merged once")
    category_reviews = _result_objects(raw.get("helper_category_reviews"), "helper category reviews")
    if [review.get("category") for review in category_reviews] != contract["helper_categories"]:
        raise CreditAnalysisError("helper category reviews are missing or reordered")
    for index, review in enumerate(category_reviews, start=1):
        _closed_result(review, {"category", "applies", "evidence_refs", "reason"}, f"helper category review {index}")
        if not isinstance(review.get("applies"), bool):
            raise CreditAnalysisError("helper category applicability is invalid")
        _holistic_result_refs(review.get("evidence_refs"), "helper category evidence", empty=True)
        if not isinstance(review.get("reason"), str) or not review["reason"].strip():
            raise CreditAnalysisError("helper category review reason is empty")
    summaries = _result_objects(raw.get("surface_summaries"), "surface summaries")
    if [summary.get("surface_id") for summary in summaries] != surface_order:
        raise CreditAnalysisError("surface summaries are missing or reordered")
    for index, summary in enumerate(summaries, start=1):
        _closed_result(
            summary,
            {"surface_id", "finding_ids", "risk_ids", "temporary_control_review_ids", "summary"},
            f"surface summary {index}",
        )
        finding_ids = _result_deduped_strings(summary.get("finding_ids"), "surface findings", empty=True)
        risk_ids = _result_deduped_strings(summary.get("risk_ids"), "surface risks", empty=True)
        review_ids = _result_deduped_strings(
            summary.get("temporary_control_review_ids"), "surface temporary controls", empty=True
        )
        if not set(finding_ids) <= set(finding_by_id) or not set(risk_ids) <= set(risk_by_id) or not set(review_ids) <= set(review_by_id):
            raise CreditAnalysisError("surface summary references an unknown result")
        if not isinstance(summary.get("summary"), str) or not summary["summary"].strip():
            raise CreditAnalysisError("surface summary text is empty")
    if not isinstance(raw.get("analysis_summary"), str) or not raw["analysis_summary"].strip():
        raise CreditAnalysisError("analysis summary is empty")
    return {
        "schema": HOLISTIC_SOL_RESULT_SCHEMA,
        "analysis_id": state["analysis_id"],
        "task_id": task["task_id"],
        "input_sha256": input_sha256,
        "surface_summaries": summaries,
        "candidate_decisions": decisions,
        "confirmed_findings": findings,
        "plausible_risks": risks,
        "temporary_control_reviews": list(review_by_id.values()),
        "temporary_control_merges": merges,
        "helper_category_reviews": category_reviews,
        "call_classifications": classifications,
        "analysis_summary": raw["analysis_summary"],
    }


def _validate_holistic_transport_value(
    value: Any,
    schema: Mapping[str, Any],
    label: str,
) -> None:
    """Validate the closed Sol transport subset used by injected runners too.

    Codex CLI enforces the same JSON Schema in production. Keeping this small
    dependency-free validator in the controller preserves standalone managed
    skill execution while making fake-runner behavior equivalent for the
    object, array, scalar, enum, and string-bound features used here.
    """

    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if value is None and "null" in expected_type:
            return
        if "string" not in expected_type or not isinstance(value, str):
            raise CreditAnalysisError(f"{label} has an invalid type")
    elif expected_type == "object":
        if not isinstance(value, Mapping):
            raise CreditAnalysisError(f"{label} must be an object")
        properties = schema.get("properties")
        required = schema.get("required")
        if not isinstance(properties, Mapping) or not isinstance(required, list):
            raise CreditAnalysisError(f"{label} schema is invalid")
        if set(value) != set(required):
            raise CreditAnalysisError(f"{label} fields are invalid")
        for key, item in value.items():
            child = properties.get(key)
            if not isinstance(child, Mapping):
                raise CreditAnalysisError(f"{label}.{key} schema is invalid")
            _validate_holistic_transport_value(item, child, f"{label}.{key}")
        return
    elif expected_type == "array":
        if not isinstance(value, list):
            raise CreditAnalysisError(f"{label} must be an array")
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            raise CreditAnalysisError(f"{label} has too few items")
        if isinstance(maximum, int) and len(value) > maximum:
            raise CreditAnalysisError(f"{label} has too many items")
        item_schema = schema.get("items")
        if not isinstance(item_schema, Mapping):
            raise CreditAnalysisError(f"{label} item schema is invalid")
        for index, item in enumerate(value):
            _validate_holistic_transport_value(
                item,
                item_schema,
                f"{label}[{index}]",
            )
        return
    elif expected_type == "string":
        if not isinstance(value, str):
            raise CreditAnalysisError(f"{label} must be text")
    elif expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise CreditAnalysisError(f"{label} must be numeric")
    elif expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise CreditAnalysisError(f"{label} must be an integer")
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            raise CreditAnalysisError(f"{label} must be boolean")
    else:
        raise CreditAnalysisError(f"{label} schema type is unsupported")
    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise CreditAnalysisError(f"{label} is empty")
        if isinstance(maximum, int) and len(value) > maximum:
            raise CreditAnalysisError(
                f"{label} exceeds its {maximum}-character semantic bound"
            )
    if "enum" in schema and value not in schema["enum"]:
        raise CreditAnalysisError(f"{label} is outside the frozen contract")
    if "minimum" in schema and value < schema["minimum"]:
        raise CreditAnalysisError(f"{label} is below its minimum")
    if "maximum" in schema and value > schema["maximum"]:
        raise CreditAnalysisError(f"{label} is above its maximum")


def _holistic_restore_alias_value(value: Any, aliases: Mapping[str, str]) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _holistic_restore_alias_value(item, aliases)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_holistic_restore_alias_value(item, aliases) for item in value]
    if isinstance(value, str):
        return aliases.get(value, value)
    return value


def _holistic_derived_workstream(
    calls: Sequence[str], workstreams: Mapping[str, str]
) -> str:
    """Return the canonical workstream; mixed input remains validator-visible."""

    observed = [workstreams[call_id] for call_id in calls if call_id in workstreams]
    return observed[0] if observed else "producer"


def _holistic_restore_sol_transport(
    raw: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    contract: Mapping[str, Any],
    compact: Mapping[str, Any],
    luna_candidate_ids: Sequence[str],
) -> dict[str, Any]:
    """Restore canonical IDs and derive every nonsemantic Sol result field."""

    alias_record = _holistic_read_sol_aliases(task, input_sha256)
    schema = _read_json(
        pathlib.Path(str(task["artifacts"]["schema"])),
        "frozen Sol transport schema",
    )
    _validate_holistic_transport_value(raw, schema, "Sol transport result")
    _, alias_to_canonical = _holistic_alias_lookups(alias_record)
    restored = _holistic_restore_alias_value(raw, alias_to_canonical)
    if not isinstance(restored, dict):
        raise CreditAnalysisError("Sol transport result is invalid")

    surface_order = list(state["manifest"]["surface_order"])
    call_order = list(state["manifest"]["call_ids"])
    call_position = {call_id: index for index, call_id in enumerate(call_order)}
    workstreams = _holistic_workstream_by_call(compact)
    luna_results = _holistic_sol_luna_results(state, compact)
    luna_candidates = {
        str(candidate["id"]): candidate
        for result in luna_results
        for candidate in result["candidates"]
    }
    candidate_position = {
        candidate_id: index
        for index, candidate_id in enumerate(luna_candidate_ids)
    }

    decisions = list(restored["candidate_decisions"])
    decisions.sort(
        key=lambda item: candidate_position.get(
            str(item.get("luna_candidate_id")),
            len(candidate_position),
        )
    )
    classifications = []
    classification_by_call: dict[str, str] = {}
    for raw_group in restored["call_classifications"]:
        group = {
            **raw_group,
            "workstream": _holistic_derived_workstream(
                [str(call_id) for call_id in raw_group["call_ids"]],
                workstreams,
            ),
        }
        classifications.append(group)
        for call_id in group["call_ids"]:
            classification_by_call[str(call_id)] = str(group["classification"])

    def outcome_surfaces(outcome_id: str, field: str) -> list[str]:
        contributed = {
            surface
            for decision in decisions
            if outcome_id in decision[field]
            for surface in luna_candidates.get(
                str(decision["luna_candidate_id"]),
                {},
            ).get("surface_ids", [])
        }
        return [surface for surface in surface_order if surface in contributed]

    findings: list[dict[str, Any]] = []
    for finding in restored["confirmed_findings"]:
        calls = [str(call_id) for call_id in finding["affected_call_ids"]]
        recurrence = dict(finding["recurrence"])
        recurrence["estimated_calls_saved_per_similar_run"] = (
            recurrence["calls_saved_per_affected_run"]
            - recurrence["additional_recurring_calls_per_affected_run"]
        ) * recurrence["affected_similar_run_frequency"]
        observed = (
            0
            if finding["waste_kind"] == "context-volume"
            else sum(
                classification_by_call.get(call_id)
                in {"avoidable_implemented", "avoidable_unimplemented"}
                for call_id in calls
            )
        )
        findings.append(
            {
                **finding,
                "evidence_narrative": (
                    "See the retained original evidence references for this finding."
                ),
                "workstream": _holistic_derived_workstream(calls, workstreams),
                "observed_avoidable_call_count": observed,
                "recurrence": recurrence,
                "contributing_surfaces": outcome_surfaces(
                    str(finding["id"]),
                    "finding_ids",
                ),
            }
        )
    findings.sort(
        key=lambda item: (
            min(
                (call_position.get(call_id, len(call_position)) for call_id in item["affected_call_ids"]),
                default=len(call_position),
            ),
            str(item["id"]),
        )
    )

    risks: list[dict[str, Any]] = []
    for risk in restored["plausible_risks"]:
        calls = [str(call_id) for call_id in risk["affected_call_ids"]]
        risks.append(
            {
                **risk,
                "workstream": _holistic_derived_workstream(calls, workstreams),
                "contributing_surfaces": outcome_surfaces(
                    str(risk["id"]),
                    "risk_ids",
                ),
            }
        )
    risks.sort(
        key=lambda item: (
            min(
                (call_position.get(call_id, len(call_position)) for call_id in item["affected_call_ids"]),
                default=len(call_position),
            ),
            str(item["id"]),
        )
    )

    reviews: list[dict[str, Any]] = []
    for review in restored["temporary_control_reviews"]:
        sources = sorted(
            [str(item) for item in review["source_luna_candidate_ids"]],
            key=lambda item: candidate_position.get(item, len(candidate_position)),
        )
        surfaces = {
            surface
            for candidate_id in sources
            for surface in luna_candidates.get(candidate_id, {}).get("surface_ids", [])
        }
        reviews.append(
            {
                **review,
                "source_luna_candidate_ids": sources,
                "contributing_surfaces": [
                    surface for surface in surface_order if surface in surfaces
                ],
            }
        )
    reviews.sort(
        key=lambda item: min(
            (
                candidate_position.get(candidate_id, len(candidate_position))
                for candidate_id in item["source_luna_candidate_ids"]
            ),
            default=len(candidate_position),
        )
    )
    review_by_id = {str(review["id"]): review for review in reviews}

    merges: list[dict[str, Any]] = []
    for merge in restored["temporary_control_merges"]:
        surfaces = {
            surface
            for review_id in merge["review_ids"]
            for surface in review_by_id.get(str(review_id), {}).get(
                "contributing_surfaces",
                [],
            )
        }
        merges.append(
            {
                **merge,
                "contributing_surfaces": [
                    surface for surface in surface_order if surface in surfaces
                ],
            }
        )
    merges.sort(key=lambda item: (str(item["owning_producer"]), str(item["control_key"])))

    category_position = {
        category: index for index, category in enumerate(contract["helper_categories"])
    }
    category_reviews = sorted(
        restored["helper_category_reviews"],
        key=lambda item: category_position.get(
            str(item.get("category")),
            len(category_position),
        ),
    )
    summaries = [
        {
            "surface_id": surface,
            "finding_ids": [
                str(finding["id"])
                for finding in findings
                if surface in finding["contributing_surfaces"]
            ],
            "risk_ids": [
                str(risk["id"])
                for risk in risks
                if surface in risk["contributing_surfaces"]
            ],
            "temporary_control_review_ids": [
                str(review["id"])
                for review in reviews
                if surface in review["contributing_surfaces"]
            ],
            "summary": (
                f"{sum(surface in item['contributing_surfaces'] for item in findings)} "
                "confirmed findings, "
                f"{sum(surface in item['contributing_surfaces'] for item in risks)} "
                "plausible risks, and "
                f"{sum(surface in item['contributing_surfaces'] for item in reviews)} "
                "temporary-control reviews."
            ),
        }
        for surface in surface_order
    ]
    return {
        "schema": HOLISTIC_SOL_RESULT_SCHEMA,
        "analysis_id": state["analysis_id"],
        "task_id": task["task_id"],
        "input_sha256": input_sha256,
        "surface_summaries": summaries,
        "candidate_decisions": decisions,
        "confirmed_findings": findings,
        "plausible_risks": risks,
        "temporary_control_reviews": reviews,
        "temporary_control_merges": merges,
        "helper_category_reviews": category_reviews,
        "call_classifications": classifications,
        "analysis_summary": (
            f"Adjudicated {len(decisions)} Luna candidates across "
            f"{len(surface_order)} surfaces into {len(findings)} confirmed findings, "
            f"{len(risks)} plausible risks, and {len(reviews)} temporary-control reviews."
        ),
    }


def _validate_holistic_task_result(
    raw: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    input_sha256: str,
    contract: Mapping[str, Any],
    compact: Mapping[str, Any],
    luna_candidate_ids: Sequence[str],
) -> dict[str, Any]:
    if task["phase"] == "luna-discovery":
        return _validate_holistic_luna_result(
            raw,
            state=state,
            task=task,
            input_sha256=input_sha256,
            contract=contract,
            compact=compact,
        )
    canonical = (
        dict(raw)
        if raw.get("schema") == HOLISTIC_SOL_RESULT_SCHEMA
        else _holistic_restore_sol_transport(
            raw,
            state=state,
            task=task,
            input_sha256=input_sha256,
            contract=contract,
            compact=compact,
            luna_candidate_ids=luna_candidate_ids,
        )
    )
    return _validate_holistic_sol_result(
        canonical,
        state=state,
        task=task,
        input_sha256=input_sha256,
        contract=contract,
        compact=compact,
        luna_candidate_ids=luna_candidate_ids,
    )


def _holistic_role(task: Mapping[str, Any]) -> str:
    return "luna" if task["phase"] == "luna-discovery" else "sol"


def _holistic_sync_child_lineage(state: dict[str, Any]) -> None:
    """Rebuild exact child-attempt lineage from the durable attempt ledger."""

    lineage: list[dict[str, Any]] = []
    for task_id in state["task_order"]:
        for attempt in state["execution"][task_id]["attempts"]:
            if attempt.get("model_invoked") is not True:
                continue
            child_ids = attempt.get("event_summary", {}).get(
                "child_session_ids", []
            )
            lineage.append(
                {
                    "analysis_id": state["analysis_id"],
                    "task_id": task_id,
                    "attempt_number": attempt["attempt_number"],
                    "ephemeral": True,
                    "child_session_ids": (
                        child_ids if isinstance(child_ids, list) else []
                    ),
                }
            )
    state["child_lineage"] = lineage


def _holistic_output_telemetry(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    validated: Mapping[str, Any],
    attempt: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Record output cost evidence without turning it into a semantic limit."""

    role = _holistic_role(task)
    reserve = int(state["model_specs"][role]["output_reserve_tokens"])
    usage_value = (
        attempt.get("event_summary", {}).get("usage", {})
        if isinstance(attempt, Mapping)
        else {}
    )
    usage = usage_value if isinstance(usage_value, Mapping) else {}
    visible_tokens = int(usage.get("output_tokens") or 0)
    reasoning_tokens = int(usage.get("reasoning_output_tokens") or 0)
    raw_chars = 0
    if isinstance(attempt, Mapping):
        raw_artifact = attempt.get("artifacts", {}).get("raw_output")
        if isinstance(raw_artifact, Mapping):
            raw_path = pathlib.Path(str(raw_artifact.get("path")))
            if raw_path.is_file() and not raw_path.is_symlink():
                raw_chars = len(raw_path.read_text(encoding="utf-8"))
    telemetry = {
        "planned_output_reserve_tokens": reserve,
        "raw_result_chars": raw_chars,
        "accepted_result_chars": _json_chars(validated),
        "duration_ms": int(attempt.get("duration_ms") or 0)
        if isinstance(attempt, Mapping)
        else 0,
        "visible_output_tokens": visible_tokens,
        "reasoning_output_tokens": reasoning_tokens,
        "total_output_tokens": visible_tokens + reasoning_tokens,
        "token_usage_available": bool(visible_tokens or reasoning_tokens),
    }
    warnings: list[dict[str, Any]] = []
    if telemetry["total_output_tokens"] > reserve:
        warnings.append(
            {
                "kind": "total-output-exceeded-planning-reserve",
                "planned_output_reserve_tokens": reserve,
                "visible_output_tokens": visible_tokens,
                "reasoning_output_tokens": reasoning_tokens,
            }
        )
    return telemetry, warnings


def _holistic_accept_result(
    *,
    state: dict[str, Any],
    task: Mapping[str, Any],
    validated: Mapping[str, Any],
    input_sha256: str,
    prompt_path: pathlib.Path,
    schema_path: pathlib.Path,
    attempt: Mapping[str, Any] | None,
    recovered: bool,
) -> None:
    result_path = pathlib.Path(str(task["artifacts"]["result"]))
    if result_path.exists():
        existing = _read_json(result_path, "recoverable holistic result")
        if existing != validated:
            raise CreditAnalysisError("recoverable holistic result is noncanonical")
    else:
        _exclusive_json(result_path, validated, "holistic model result")
    role = _holistic_role(task)
    execution = state["execution"][task["task_id"]]
    if attempt is not None:
        accepted_attempt = dict(attempt)
        accepted_attempt["outcome"] = "accepted"
        accepted_attempt["error"] = None
        execution["attempts"].append(accepted_attempt)
    telemetry_attempt = attempt
    if telemetry_attempt is None and execution["attempts"]:
        telemetry_attempt = execution["attempts"][-1]
    output_telemetry, output_budget_warnings = _holistic_output_telemetry(
        state=state,
        task=task,
        validated=validated,
        attempt=telemetry_attempt,
    )
    _holistic_sync_child_lineage(state)
    execution["status"] = "complete"
    execution["result"] = {
        "path": str(result_path),
        "sha256": _file_hash(result_path),
        "content_hash": _content_hash(validated),
        "analysis_id": state["analysis_id"],
        "task_id": task["task_id"],
        "phase": task["phase"],
        "model": state["model_specs"][role]["model"],
        "reasoning_effort": state["model_specs"][role]["reasoning_effort"],
        "input_sha256": input_sha256,
        "prompt_sha256": _file_hash(prompt_path),
        "schema_sha256": _file_hash(schema_path),
        "aliases_sha256": (
            _file_hash(pathlib.Path(str(task["artifacts"]["aliases"])))
            if task["phase"] == "sol-adjudication"
            else None
        ),
        "output_telemetry": output_telemetry,
        "output_budget_warnings": output_budget_warnings,
        "recovered_without_model_call": recovered,
    }
    state["model_calls"][role] += 1
    _holistic_save_state(state)


def _holistic_recoverable_raw(
    state: Mapping[str, Any], task: Mapping[str, Any], input_sha256: str
) -> Mapping[str, Any] | None:
    attempts = state["execution"][task["task_id"]]["attempts"]
    for attempt in reversed(attempts):
        if (
            attempt.get("outcome") != "validation-error"
            or attempt.get("input_sha256") != input_sha256
        ):
            continue
        artifact = attempt.get("artifacts", {}).get("raw_output")
        if isinstance(artifact, Mapping):
            return _read_json(
                pathlib.Path(str(artifact["path"])),
                "recoverable holistic output",
            )
    return None


def _holistic_final(
    state: Mapping[str, Any], evidence: Mapping[str, Any], sol: Mapping[str, Any]
) -> dict[str, Any]:
    findings = [
        {**finding, "volume": _aggregate_finding_volume(finding, evidence)}
        for finding in sol["confirmed_findings"]
    ]
    findings.sort(key=_finding_presentation_key)
    classification_totals: Counter[str] = Counter()
    workstream_totals: dict[str, Counter[str]] = {
        "producer": Counter(),
        "analysis-overhead": Counter(),
    }
    protocol_overhead = 0
    for group in sol["call_classifications"]:
        count = len(group["call_ids"])
        classification_totals[group["classification"]] += count
        workstream_totals[group["workstream"]][group["classification"]] += count
        if group["reason_code"] == "protocol-overhead":
            protocol_overhead += count
    luna_results = _holistic_luna_results(state, state["manifest"])
    discovery_kinds = Counter(
        candidate["kind"] for result in luna_results for candidate in result["candidates"]
    )
    return {
        "schema": HOLISTIC_FINAL_SCHEMA,
        "analysis_id": state["analysis_id"],
        "action": state["action"],
        "mode": state["mode"],
        "mutation_authority": False,
        "source": state["source"],
        "window": state["window"],
        "lineage": {
            **state["lineage"],
            "excluded_own_descendant_task_ids": list(
                dict.fromkeys(
                    child["task_id"] for child in state["child_lineage"]
                )
            ),
            "created_child_tasks": state["child_lineage"],
        },
        "evidence": state["evidence"],
        "manifest": {
            "path": state["manifest"]["path"],
            "sha256": state["manifest"]["sha256"],
            "surface_order": state["manifest"]["surface_order"],
            "projected_luna_calls": state["manifest"]["projected_luna_calls"],
            "projected_sol_calls": 1,
            "projected_semantic_calls": state["manifest"]["projected_semantic_calls"],
            "shared_luna_packets": len(state["manifest"]["luna_tasks"]),
            "shared_candidate_count": len(state["manifest"]["candidate_ids"]),
            "candidate_coverage_sha256": state["manifest"]["candidate_ids_sha256"],
            "unclassified_calls": 0,
        },
        "model_calls": {
            "actual_luna": state["model_attempts"]["luna"],
            "actual_sol": state["model_attempts"]["sol"],
            "accepted_luna": state["model_calls"]["luna"],
            "accepted_sol": state["model_calls"]["sol"],
            "bookkeeping": 0,
        },
        "luna_discovery": {
            "candidate_count": sum(discovery_kinds.values()),
            "candidate_kind_totals": dict(sorted(discovery_kinds.items())),
            "packet_coverage": [result["coverage"] for result in luna_results],
        },
        "surface_summaries": sol["surface_summaries"],
        "candidate_decisions": sol["candidate_decisions"],
        "confirmed_findings": findings,
        "plausible_risks": sol["plausible_risks"],
        "temporary_control_reviews": sol["temporary_control_reviews"],
        "temporary_control_merges": sol["temporary_control_merges"],
        "helper_category_reviews": sol["helper_category_reviews"],
        "call_classifications": sol["call_classifications"],
        "classification_totals": {
            **{
                classification: classification_totals[classification]
                for classification in state.get("classification_order", [
                    "necessary",
                    "avoidable_implemented",
                    "avoidable_unimplemented",
                    "reviewed_no_confirmed_waste",
                    "unassessed",
                ])
            },
            "protocol_overhead": protocol_overhead,
        },
        "workstream_classification_totals": {
            workstream: {
                classification: totals[classification]
                for classification in (
                    "necessary",
                    "avoidable_implemented",
                    "avoidable_unimplemented",
                    "reviewed_no_confirmed_waste",
                    "unassessed",
                )
            }
            for workstream, totals in workstream_totals.items()
        },
        "analysis_summary": sol["analysis_summary"],
        "deterministic_totals": evidence["totals"],
        "pricing": evidence["pricing"],
        "retained_artifacts": {
            "state": state["paths"]["state"],
            "evidence": state["evidence"]["path"],
            "manifest": state["manifest"]["path"],
            "compact_evidence": state["manifest"]["compact_evidence"]["path"],
            "orchestration_root": state["paths"]["orchestration_root"],
        },
    }


def _render_holistic_report(final: Mapping[str, Any]) -> str:
    findings = final["confirmed_findings"]
    outstanding = [
        finding for finding in findings if finding["implementation_status"] == "unimplemented"
    ]
    implemented = len(findings) - len(outstanding)
    lines = [
        f"Confirmed: {len(findings)}; outstanding: {len(outstanding)}; already addressed: {implemented}",
        "",
        (
            f"Luna calls: {final['model_calls']['actual_luna']} "
            f"(projected {final['manifest']['projected_luna_calls']}); "
            f"Sol calls: {final['model_calls']['actual_sol']} (projected 1); "
            "bookkeeping calls: 0."
        ),
        "",
    ]
    for workstream, title in (
        ("producer", "Producer work"),
        ("analysis-overhead", "Analysis-generated work"),
    ):
        selected = [finding for finding in outstanding if finding["workstream"] == workstream]
        if not selected:
            continue
        lines.extend([f"# {title}", ""])
        for finding in selected:
            recurrence = finding["recurrence"]
            volume = finding["volume"]
            lines.extend(
                [
                    f"## {finding['title']}",
                    "",
                    f"Problem: {finding['problem_summary']}",
                    "",
                    (
                        f"Evidence: {len(finding['affected_call_ids'])} affected calls; "
                        f"{volume['input_tokens']} input, {volume['cached_input_tokens']} "
                        f"cached-input, {volume['output_tokens']} output tokens; "
                        f"{volume['tool_argument_chars']} tool-argument and "
                        f"{volume['tool_result_chars']} tool-result characters."
                    ),
                    "",
                    f"Fix: {finding['proposed_durable_control']} Owner: {finding['producer_owner']}.",
                    "",
                    "Verification: " + "; ".join(finding["targeted_verification"]),
                    "",
                    (
                        f"Savings: {finding['observed_avoidable_call_count']} observed calls; "
                        f"{recurrence['estimated_calls_saved_per_similar_run']} expected calls "
                        f"per similar run; {finding['one_time_implementation_cost']['estimated_model_calls']} "
                        f"implementation calls; {finding['complexity']} ongoing complexity."
                    ),
                    "",
                ]
            )
    for risk in final["plausible_risks"]:
        lines.extend(
            [
                "## Plausible risk",
                "",
                f"Observed: {risk['description']}",
                "",
                "Unknown: " + "; ".join(risk["competing_explanations"]),
                "",
                f"Why not confirmed: {risk['missing_fact']}",
                "",
                "How to confirm: " + "; ".join(risk["verification_needed"]),
                "",
            ]
        )
    totals = final["classification_totals"]
    producer = final["workstream_classification_totals"]["producer"]
    analysis = final["workstream_classification_totals"]["analysis-overhead"]
    lines.extend(
        [
            "# Call accounting",
            "",
            (
                f"Necessary: {totals['necessary']}; protocol overhead: "
                f"{totals['protocol_overhead']}; avoidable implemented: "
                f"{totals['avoidable_implemented']}; avoidable unimplemented: "
                f"{totals['avoidable_unimplemented']}; reviewed without confirmed waste: "
                f"{totals['reviewed_no_confirmed_waste']}; unassessed: "
                f"{totals['unassessed']}; unclassified: 0."
            ),
            "",
            (
                "Producer calls — necessary: "
                f"{producer['necessary']}; avoidable: "
                f"{producer['avoidable_implemented'] + producer['avoidable_unimplemented']}; "
                f"reviewed: {producer['reviewed_no_confirmed_waste']}; "
                f"unassessed: {producer['unassessed']}."
            ),
            "",
            (
                "Analysis-generated calls — necessary: "
                f"{analysis['necessary']}; avoidable: "
                f"{analysis['avoidable_implemented'] + analysis['avoidable_unimplemented']}; "
                f"reviewed: {analysis['reviewed_no_confirmed_waste']}; "
                f"unassessed: {analysis['unassessed']}."
            ),
            "",
            f"Retained result: {final['retained_artifacts']['state']}",
            "",
        ]
    )
    return "\n".join(lines)


def _finalize_holistic(state: dict[str, Any], evidence: Mapping[str, Any]) -> None:
    if state["model_calls"]["luna"] != state["manifest"]["projected_luna_calls"]:
        raise CreditAnalysisError("accepted Luna calls do not match the frozen plan")
    if state["model_calls"]["sol"] != 1:
        raise CreditAnalysisError("holistic analysis did not use exactly one Sol call")
    sol_task = state["manifest"]["sol_task"]
    sol_record = state["execution"][sol_task["task_id"]]["result"]
    sol = _read_json(pathlib.Path(sol_record["path"]), "accepted Sol result")
    final = _holistic_final(state, evidence, sol)
    final_path = pathlib.Path(state["paths"]["final_result"])
    _write_or_verify_json(final_path, final, "holistic final result")
    report_path = pathlib.Path(state["paths"]["report"])
    report_sha = _write_or_verify_text(
        report_path,
        _render_holistic_report(final),
        "holistic final report",
    )
    state["phase"] = "complete"
    state["final_result"] = {
        "path": str(final_path),
        "sha256": _file_hash(final_path),
        "content_hash": _content_hash(final),
        "report_path": str(report_path),
        "report_sha256": report_sha,
    }
    _cleanup_orchestration_transient(state)
    _holistic_save_state(state)


def command_execute_orchestration(
    state_path: pathlib.Path,
    *,
    runner: Any | None = None,
    available_models: set[str] | Mapping[str, Mapping[str, Any]] | None = None,
    task_limit: int | None = None,
) -> dict[str, Any]:
    """Execute or resume the finite queue with no model-mediated polling."""

    state, evidence, contract, compact = _holistic_read_state(state_path)
    if state["phase"] == "complete":
        return _holistic_public_status(state)
    catalog = (
        available_models
        if available_models is not None
        else (
            runner.available_models
            if runner is not None and hasattr(runner, "available_models")
            else _codex_model_catalog()
        )
    )
    current_specs = _holistic_model_specs(contract, catalog)
    for role in ("luna", "sol"):
        planned = state["model_specs"][role]
        current = current_specs[role]
        if (
            current["model"] != planned["model"]
            or current["reasoning_effort"] != planned["reasoning_effort"]
            or current["effective_context_tokens"] < planned["effective_context_tokens"]
        ):
            raise CreditAnalysisError(f"{role} model capability changed after planning")
    if task_limit is not None and (
        not isinstance(task_limit, int) or isinstance(task_limit, bool) or task_limit < 0
    ):
        raise CreditAnalysisError("task_limit must be a nonnegative integer")
    tasks = _holistic_task_map(state["manifest"])
    completed_this_run = 0
    state["phase"] = "executing"
    _holistic_save_state(state)
    for task_id in state["task_order"]:
        execution = state["execution"][task_id]
        if execution["status"] == "complete":
            continue
        if task_limit is not None and completed_this_run >= task_limit:
            break
        task = tasks[task_id]
        incomplete_dependencies = [
            dependency
            for dependency in task["dependencies"]
            if state["execution"][dependency]["status"] != "complete"
        ]
        if incomplete_dependencies:
            raise CreditAnalysisError(
                f"model task dependency is incomplete: {incomplete_dependencies[0]}"
            )
        payload, input_sha, prompt_path, schema_path, luna_candidate_ids = (
            _holistic_prepare_task(state, evidence, contract, compact, task)
        )
        result_path = pathlib.Path(str(task["artifacts"]["result"]))
        if result_path.is_file() and not result_path.is_symlink():
            persisted_raw = _read_json(result_path, "recoverable holistic result")
            validated = _validate_holistic_task_result(
                persisted_raw,
                state=state,
                task=task,
                input_sha256=input_sha,
                contract=contract,
                compact=compact,
                luna_candidate_ids=luna_candidate_ids,
            )
            _holistic_accept_result(
                state=state,
                task=task,
                validated=validated,
                input_sha256=input_sha,
                prompt_path=prompt_path,
                schema_path=schema_path,
                attempt=None,
                recovered=True,
            )
            completed_this_run += 1
            continue
        recoverable = _holistic_recoverable_raw(state, task, input_sha)
        if recoverable is not None:
            try:
                validated = _validate_holistic_task_result(
                    recoverable,
                    state=state,
                    task=task,
                    input_sha256=input_sha,
                    contract=contract,
                    compact=compact,
                    luna_candidate_ids=luna_candidate_ids,
                )
            except CreditAnalysisError:
                pass
            else:
                _holistic_accept_result(
                    state=state,
                    task=task,
                    validated=validated,
                    input_sha256=input_sha,
                    prompt_path=prompt_path,
                    schema_path=schema_path,
                    attempt=None,
                    recovered=True,
                )
                completed_this_run += 1
                continue
        role = _holistic_role(task)
        model = str(state["model_specs"][role]["model"])
        effort = str(state["model_specs"][role]["reasoning_effort"])
        runtime_task = {**task, "reasoning_effort": effort}
        attempt_number = len(execution["attempts"]) + 1
        attempt_dir = pathlib.Path(str(task["artifacts"]["attempts"])) / f"attempt-{attempt_number:03d}"
        if runner is None:
            model_raw, attempt = _run_codex_child(
                analysis_id=str(state["analysis_id"]),
                model=model,
                reasoning_effort=effort,
                task=runtime_task,
                prompt_path=prompt_path,
                schema_path=schema_path,
                attempt_dir=attempt_dir,
                orchestration_root=pathlib.Path(state["paths"]["orchestration_root"]),
            )
        else:
            model_raw, attempt = _invoke_injected_runner(
                runner,
                model=model,
                task=runtime_task,
                prompt_path=prompt_path,
                schema_path=schema_path,
                input_payload=payload,
                input_sha256=input_sha,
                attempt_dir=attempt_dir,
            )
        attempt = {**attempt, "reasoning_effort": effort}
        attempt = _bind_attempt_record(
            attempt,
            state=state,
            task=runtime_task,
            input_sha256=input_sha,
            attempt_number=attempt_number,
        )
        if attempt["model_invoked"]:
            state["model_attempts"][role] += 1
        if model_raw is None:
            failed = {**attempt, "outcome": "runner-error"}
            execution["attempts"].append(failed)
            _holistic_sync_child_lineage(state)
            _holistic_save_state(state)
            raise CreditAnalysisError(str(attempt.get("error") or "model task produced no result"))
        try:
            validated = _validate_holistic_task_result(
                model_raw,
                state=state,
                task=task,
                input_sha256=input_sha,
                contract=contract,
                compact=compact,
                luna_candidate_ids=luna_candidate_ids,
            )
        except CreditAnalysisError as exc:
            failed = {**attempt, "outcome": "validation-error", "error": str(exc)}
            execution["attempts"].append(failed)
            _holistic_sync_child_lineage(state)
            _holistic_save_state(state)
            raise
        _holistic_accept_result(
            state=state,
            task=task,
            validated=validated,
            input_sha256=input_sha,
            prompt_path=prompt_path,
            schema_path=schema_path,
            attempt=attempt,
            recovered=False,
        )
        completed_this_run += 1
    if all(state["execution"][task_id]["status"] == "complete" for task_id in state["task_order"]):
        _finalize_holistic(state, evidence)
    else:
        _holistic_save_state(state)
    return _holistic_public_status(state)

__all__ = (
    "ANALYSIS_SUMMARY_FIELDS",
    "CALL_CLASSIFICATION_FIELDS",
    "CONFIRMATION_ASSESSMENT_FIELDS",
    "CONFIRMATION_CHILD_ASSESSMENT_FIELDS",
    "CONFIRMATION_CHILD_FINDING_FIELDS",
    "CONFIRMATION_CHILD_RESULT_FIELDS",
    "CONFIRMATION_CHILD_RISK_FIELDS",
    "CONFIRMATION_FINDING_FIELDS",
    "CONFIRMATION_RESULT_FIELDS",
    "CONFIRMATION_RISK_FIELDS",
    "FINDING_GROUP_FIELDS",
    "LUNA_ASSESSMENT_FIELDS",
    "LUNA_CHILD_ASSESSMENT_FIELDS",
    "LUNA_CHILD_FINDING_FIELDS",
    "LUNA_CHILD_RESULT_FIELDS",
    "LUNA_CHILD_RISK_FIELDS",
    "LUNA_CHILD_TEMPORARY_FIELDS",
    "LUNA_FINDING_FIELDS",
    "LUNA_PRIMARY_CHILD_ASSESSMENT_FIELDS",
    "LUNA_RESULT_FIELDS",
    "LUNA_RISK_FIELDS",
    "LUNA_SHARED_CONSOLIDATION_CHILD_ASSESSMENT_FIELDS",
    "LUNA_TEMPORARY_FIELDS",
    "ORCHESTRATION_PRODUCER_GROUP_FIELDS",
    "OUTCOME_KEYS",
    "SURFACE_EVIDENCE_KEYWORDS",
    "SYNTHESIS_RESULT_FIELDS",
    "TEMPORARY_CONTRIBUTION_FIELDS",
    "TEMPORARY_MERGE_FIELDS",
    "TEMPORARY_REVIEW_FIELDS",
    "CANONICAL_REFERENCE_RE",
    "WORKSPACE_LOCATION_RE",
    "_aggregate_finding_volume",
    "_bind_attempt_record",
    "_canonical_artifact_references",
    "_canonical_projection",
    "_canonical_references_from_evidence",
    "_canonical_workspace_target",
    "_cleanup_orchestration_transient",
    "_closed_result",
    "_codex_child_command",
    "_codex_model_catalog",
    "_collect_canonical_state_snapshot",
    "_collect_holistic_evidence",
    "_exclusive_text",
    "_finalize_holistic",
    "_has_failure_telemetry",
    "_holistic_accept_result",
    "_holistic_call_classifications",
    "_holistic_compact_bundle",
    "_holistic_episodes",
    "_holistic_final",
    "_holistic_luna_payload",
    "_holistic_luna_results",
    "_holistic_luna_schema",
    "_holistic_model_specs",
    "_holistic_partition",
    "_holistic_prepare_task",
    "_holistic_prior_analysis_activity",
    "_holistic_projection",
    "_holistic_prompt",
    "_holistic_public_status",
    "_holistic_read_state",
    "_holistic_reconcile_findings",
    "_holistic_recoverable_raw",
    "_holistic_result_refs",
    "_holistic_role",
    "_holistic_save_state",
    "_holistic_sol_input",
    "_holistic_sol_schema",
    "_holistic_split_episode",
    "_holistic_state_paths",
    "_holistic_surface_ids",
    "_holistic_sync_child_lineage",
    "_holistic_task_map",
    "_holistic_workstream_by_call",
    "_invoke_injected_runner",
    "_jsonl_event_summary",
    "_observable_high_signal_reasons",
    "_process_is_alive",
    "_relevant_segments",
    "_render_holistic_report",
    "_result_deduped_strings",
    "_result_objects",
    "_review_record_index",
    "_run_codex_child",
    "_run_index",
    "_shared_relevant_segments",
    "_structured_outcome",
    "_surface_order_for_request",
    "_surface_reference_text",
    "_task_artifact_paths",
    "_terminate_process_tree",
    "_validate_holistic_finding",
    "_validate_holistic_luna_result",
    "_validate_holistic_manifest",
    "_validate_holistic_sol_result",
    "_validate_holistic_task_result",
    "_validate_recurrence_inputs",
    "_write_or_verify_task_input",
    "_write_or_verify_text",
    "command_execute_orchestration",
    "command_orchestration_status",
    "command_plan_orchestration",
)
