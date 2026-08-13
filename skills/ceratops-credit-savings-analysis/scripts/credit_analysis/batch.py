"""Recent-thread batch orchestration layered over the shared controller core."""
# ruff: noqa: F401,F403,F405,I001

from __future__ import annotations

from .core import *


def _holistic_controller() -> ModuleType:
    """Resolve the owning per-thread controller lazily to avoid an import cycle."""

    from . import holistic

    return holistic

def _project_selector(raw: Any) -> dict[str, str] | None:
    """Normalize one exact project selector without filesystem discovery."""

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CreditAnalysisError("project selector must be an object or null")
    _closed(raw, PROJECT_SELECTOR_FIELDS, "project selector")
    kind = raw.get("kind")
    value = raw.get("value")
    if kind not in {"name", "path", "repository_url"}:
        raise CreditAnalysisError("project selector kind is invalid")
    if not isinstance(value, str) or not value.strip():
        raise CreditAnalysisError("project selector value must be nonempty")
    normalized = value.strip()
    if kind == "name":
        normalized = normalized.casefold()
    elif kind == "repository_url":
        normalized = normalized.rstrip("/").removesuffix(".git").casefold()
    else:
        candidate = pathlib.Path(normalized).expanduser()
        if not candidate.is_absolute():
            raise CreditAnalysisError("project path selector must be absolute")
        normalized = os.path.normcase(os.path.normpath(str(candidate.resolve())))
    return {"kind": str(kind), "value": normalized}


def _project_matches(
    metadata: Mapping[str, Any],
    selector: Mapping[str, str] | None,
) -> bool:
    if selector is None:
        return True
    kind = selector["kind"]
    value = selector["value"]
    if kind == "name":
        aliases = metadata.get("project_aliases")
        return isinstance(aliases, list) and value in aliases
    if kind == "repository_url":
        return metadata.get("normalized_repository_url") == value
    cwd = metadata.get("normalized_cwd")
    if not isinstance(cwd, str):
        return False
    try:
        return pathlib.Path(cwd) == pathlib.Path(value) or pathlib.Path(
            cwd
        ).is_relative_to(pathlib.Path(value))
    except (OSError, ValueError):
        return False


def _batch_request_paths(
    request: Mapping[str, Any],
) -> tuple[pathlib.Path, dict[str, pathlib.Path]]:
    task_root = _task_directory(request.get("task_temp_root"), "task_temp_root")
    manifest_value = request.get("manifest_output")
    if not isinstance(manifest_value, str) or not manifest_value:
        raise CreditAnalysisError("manifest_output must be nonempty text")
    manifest = pathlib.Path(manifest_value).expanduser().resolve()
    if not manifest.parent.is_dir():
        raise CreditAnalysisError("manifest output directory does not exist")
    if manifest.is_symlink() or manifest.is_dir():
        raise CreditAnalysisError("manifest output must be a regular-file path")
    paths = {
        "state": task_root / "batch-state.json",
        "manifest": manifest,
        "requests_dir": task_root / "requests",
        "analyses_dir": task_root / "analyses",
        "evidence_dir": task_root / "evidence",
        "index": task_root / "batch-results.jsonl",
        "batch_summary_context": task_root / "batch-summary-context.json",
        "batch_summary_result": task_root / "batch-summary.json",
        "final_result": task_root / "batch-final-machine-result.json",
    }
    collisions = [path.resolve() for path in paths.values()]
    if len(collisions) != len(set(collisions)):
        raise CreditAnalysisError("batch controller paths must be distinct")
    for key in (
        "manifest",
        "requests_dir",
        "analyses_dir",
        "evidence_dir",
        "batch_summary_context",
        "batch_summary_result",
    ):
        try:
            paths[key].resolve().relative_to(task_root)
        except ValueError as exc:
            raise CreditAnalysisError(f"batch {key} escapes task_temp_root") from exc
    return task_root, paths


def _validated_batch_request(
    request_path: pathlib.Path,
    contract: Mapping[str, Any],
    ledger: ModuleType,
) -> dict[str, Any]:
    """Validate one bounded, analysis-only batch request before side effects."""

    request = _read_json(request_path, "batch request")
    _closed(request, BATCH_REQUEST_FIELDS, "batch request")
    if request.get("schema") != contract["batch_request_schema"]:
        raise CreditAnalysisError(
            f"batch request schema must be {contract['batch_request_schema']}"
        )
    if request.get("action") != "full-analysis" or request.get("mode") != "per-thread-batch":
        raise CreditAnalysisError("batch requests must use full-analysis per-thread-batch")
    if request.get("mutation_authority") is not False:
        raise CreditAnalysisError("mutation_authority must be false")
    if request.get("expected_surface_contract_version") != contract[
        "surface_contract_version"
    ]:
        raise CreditAnalysisError("surface contract version mismatch")
    if request.get("expected_source_selection_contract_version") != contract[
        "source_selection_contract_version"
    ]:
        raise CreditAnalysisError("source selection contract version mismatch")
    selector_raw = request.get("selector")
    if not isinstance(selector_raw, dict):
        raise CreditAnalysisError("batch selector must be an object")
    _closed(selector_raw, BATCH_SELECTOR_FIELDS, "batch selector")
    kind = selector_raw.get("kind")
    count = selector_raw.get("count")
    days = selector_raw.get("days")
    if kind == "recent_threads":
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count < 1
            or days is not None
        ):
            raise CreditAnalysisError(
                "recent_threads requires a positive count and null days"
            )
    elif kind == "recent_days":
        if (
            not isinstance(days, int)
            or isinstance(days, bool)
            or days < 1
            or count is not None
        ):
            raise CreditAnalysisError(
                "recent_days requires positive days and a null count"
            )
    else:
        raise CreditAnalysisError("batch selector kind is invalid")
    project = _project_selector(selector_raw.get("project"))
    try:
        as_of = ledger.parse_utc_timestamp(request.get("as_of"), "batch as_of")
    except RuntimeError as exc:
        raise CreditAnalysisError(str(exc)) from exc
    if as_of > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
        raise CreditAnalysisError("batch as_of cannot be in the future")
    task_root, paths = _batch_request_paths(request)
    reserved_existing = [
        path for path in paths.values() if path.exists() or path.is_symlink()
    ]
    if reserved_existing:
        raise CreditAnalysisError(
            f"task_temp_root already contains batch controller state: {reserved_existing[0].name}"
        )
    pricing_value = request.get("pricing_profile")
    pricing = (
        None
        if pricing_value is None
        else _existing_file(pricing_value, "pricing profile")
    )
    if pricing is not None and pricing.resolve() in {
        path.resolve() for path in paths.values()
    }:
        raise CreditAnalysisError("pricing profile collides with a batch path")
    selector = {
        "kind": kind,
        "count": count,
        "days": days,
        "project": project,
    }
    return {
        "request": request,
        "request_path": request_path,
        "request_hash": _file_hash(request_path),
        "task_root": task_root,
        "paths": paths,
        "selector": selector,
        "as_of": as_of,
        "pricing": pricing,
    }


def _select_batch_candidates(
    request: Mapping[str, Any],
    ledger: ModuleType,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
    """Freeze index-ordered candidates and reject ambiguous project names."""

    index = ledger.load_thread_index()
    as_of = request["as_of"]
    selector = request["selector"]
    assert isinstance(as_of, dt.datetime)
    assert isinstance(selector, Mapping)
    start = (
        as_of - dt.timedelta(days=int(selector["days"]))
        if selector["kind"] == "recent_days"
        else None
    )
    candidates: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    for entry in index["entries"]:
        updated_at = ledger.parse_utc_timestamp(
            entry["updated_at"], "thread index updated_at"
        )
        if updated_at > as_of or start is not None and updated_at < start:
            continue
        thread_id = entry["thread_id"]
        try:
            session = ledger.resolve_thread_session(thread_id)
            metadata = ledger.read_session_source_metadata(
                session,
                expected_thread_id=thread_id,
            )
        except (OSError, RuntimeError, ValueError):
            exclusions.append(
                {
                    "thread_id": thread_id,
                    "reason": "unresolvable-session-or-metadata",
                }
            )
            continue
        if not _project_matches(metadata, selector["project"]):
            continue
        candidates.append(
            {
                "thread_id": thread_id,
                "thread_name": entry["thread_name"],
                "updated_at": entry["updated_at"],
                "session": str(session),
                "project": {
                    "key": metadata["project_key"],
                    "cwd": metadata["cwd"],
                    "repository_url": metadata["repository_url"],
                },
            }
        )
    project = selector["project"]
    if isinstance(project, Mapping) and project.get("kind") == "name":
        project_keys = {
            candidate["project"]["key"]
            for candidate in candidates
            if candidate["project"]["key"] is not None
        }
        if len(project_keys) > 1:
            raise CreditAnalysisError(
                "project name is ambiguous; use an exact path or repository URL"
            )
    if not candidates:
        raise CreditAnalysisError("batch selector matched no resolvable threads")
    return index, candidates, exclusions


def _batch_item_paths(
    state: Mapping[str, Any],
    ordinal: int,
    thread_id: str,
) -> dict[str, pathlib.Path]:
    stem = f"{ordinal:03d}-{thread_id}"
    paths = state["paths"]
    analysis_root = pathlib.Path(paths["analyses_dir"]) / stem
    return {
        "request": pathlib.Path(paths["requests_dir"]) / f"{stem}.json",
        "analysis_root": analysis_root,
        "evidence": analysis_root / "evidence.json",
    }


def _write_or_verify_json(
    path: pathlib.Path,
    value: Mapping[str, Any],
    label: str,
) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise CreditAnalysisError(f"{label} must be a regular file")
        if _content_hash(_read_json(path, label)) != _content_hash(value):
            raise CreditAnalysisError(f"conflicting {label} already exists")
        return
    _exclusive_json(path, value, label)


def _save_batch_state(state: Mapping[str, Any]) -> None:
    _atomic_json(pathlib.Path(state["paths"]["state"]), state, "batch state")


def _batch_manifest(
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    requested_count = state["selector"]["count"]
    return {
        "schema": contract["batch_manifest_schema"],
        "batch_id": state["batch_id"],
        "action": "full-analysis",
        "mode": "per-thread-batch",
        "mutation_authority": False,
        "surface_contract_version": state["surface_contract_version"],
        "source_selection_contract_version": state[
            "source_selection_contract_version"
        ],
        "selector": state["selector"],
        "as_of": state["as_of"],
        "source_index": state["source_index"],
        "selection": {
            "requested_count": requested_count,
            "selected_count": len(state["items"]),
            "excluded_count": len(state["exclusions"]),
            "unexamined_candidate_count": len(state["candidates"])
            - state["candidate_index"],
        },
        "items": state["items"],
        "exclusions": state["exclusions"],
    }


def _batch_item_record(
    candidate: Mapping[str, Any],
    child_paths: Mapping[str, pathlib.Path],
    *,
    ordinal: int,
    source_fingerprint: str,
) -> dict[str, Any]:
    analysis_root = child_paths["analysis_root"]
    return {
        "ordinal": ordinal,
        "thread_id": candidate["thread_id"],
        "thread_name": candidate["thread_name"],
        "updated_at": candidate["updated_at"],
        "project": candidate["project"],
        "session": candidate["session"],
        "source_fingerprint": source_fingerprint,
        "request_path": str(child_paths["request"]),
        "state_path": str(analysis_root / "state.json"),
        "evidence_path": str(child_paths["evidence"]),
        "final_result_path": str(analysis_root / "final-machine-result.json"),
    }


def _recover_prepared_batch_item(
    candidate: Mapping[str, Any],
    child_paths: Mapping[str, pathlib.Path],
    contract: Mapping[str, Any],
    *,
    ordinal: int,
) -> dict[str, Any] | None:
    """Recover a child committed before its outer batch-state checkpoint."""

    state_path = child_paths["analysis_root"] / "state.json"
    if not state_path.exists():
        return None
    child_state, evidence, child_contract, _ = (
        _holistic_controller()._holistic_read_state(state_path)
    )
    request_path = pathlib.Path(child_state["immutable_artifacts"]["request"]["path"])
    if request_path.resolve() != child_paths["request"].resolve():
        raise CreditAnalysisError("prepared batch child request path changed")
    if pathlib.Path(child_state["evidence"]["path"]).resolve() != child_paths[
        "evidence"
    ].resolve():
        raise CreditAnalysisError("prepared batch child evidence path changed")
    projected_calls = child_state.get("manifest", {}).get(
        "projected_semantic_calls"
    )
    if (
        child_state["action"] != "full-analysis"
        or child_state["mode"] != "full-analysis"
        or child_contract["surface_contract_version"]
        != contract["surface_contract_version"]
        or child_state["source"].get("kind") != "thread_id"
        or child_state["source"].get("value") != candidate["thread_id"]
        or pathlib.Path(child_state["source"]["resolved_session"]).resolve()
        != pathlib.Path(candidate["session"]).resolve()
        or pathlib.Path(str(evidence.get("session"))).resolve()
        != pathlib.Path(candidate["session"]).resolve()
        or evidence.get("source_fingerprint") != child_state["source"]["fingerprint"]
        or evidence.get("collection", {}).get("session_reads") != 1
        or not isinstance(projected_calls, int)
        or isinstance(projected_calls, bool)
        or projected_calls < 2
    ):
        raise CreditAnalysisError("prepared batch child identity is invalid")
    return _batch_item_record(
        candidate,
        child_paths,
        ordinal=ordinal,
        source_fingerprint=child_state["source"]["fingerprint"],
    )


def _resume_batch_preparation(
    state: dict[str, Any],
    contract: Mapping[str, Any],
) -> None:
    """Plan each holistic child once and checkpoint every retained controller."""

    if state["phase"] != "preparing":
        return
    selector = state["selector"]
    target_count = selector["count"]
    pricing_record = state["immutable_artifacts"]["pricing_profile"]
    pricing = (
        pathlib.Path(pricing_record["path"])
        if isinstance(pricing_record, Mapping)
        else None
    )
    holistic = _holistic_controller()
    available_models: Mapping[str, Mapping[str, Any]] | None = None
    while state["candidate_index"] < len(state["candidates"]):
        if isinstance(target_count, int) and len(state["items"]) >= target_count:
            break
        candidate = state["candidates"][state["candidate_index"]]
        ordinal = len(state["items"]) + 1
        child_paths = _batch_item_paths(state, ordinal, candidate["thread_id"])
        recovered = _recover_prepared_batch_item(
            candidate,
            child_paths,
            contract,
            ordinal=ordinal,
        )
        if recovered is not None:
            state["items"].append(recovered)
            state["candidate_index"] += 1
            _save_batch_state(state)
            continue
        child_paths["analysis_root"].mkdir()
        child_request = {
            "schema": contract["request_schema"],
            "action": "full-analysis",
            "mode": "full-analysis",
            "source": {"thread_id": candidate["thread_id"], "session": None},
            "window": {
                "mode": "full_thread",
                "last_runs": None,
                "turn_ids": [],
            },
            "task_temp_root": str(child_paths["analysis_root"]),
            "evidence_output": str(child_paths["evidence"]),
            "pricing_profile": str(pricing) if pricing is not None else None,
            "expected_surface_contract_version": state["surface_contract_version"],
            "mutation_authority": False,
        }
        _write_or_verify_json(
            child_paths["request"], child_request, "batch child request"
        )
        try:
            if available_models is None:
                available_models = holistic._codex_model_catalog()
            child_status = holistic.command_plan_orchestration(
                child_paths["request"],
                available_models=available_models,
            )
        except CreditAnalysisError as exc:
            if str(exc) != "selected completed-run window has no model calls":
                raise CreditAnalysisError(
                    f"batch holistic planning failed for {candidate['thread_id']}: {exc}"
                ) from exc
            child_paths["request"].unlink()
            child_paths["analysis_root"].rmdir()
            state["exclusions"].append(
                {
                    "thread_id": candidate["thread_id"],
                    "reason": "no-completed-model-calls",
                }
            )
            state["candidate_index"] += 1
            _save_batch_state(state)
            continue
        child_state, evidence, _, _ = holistic._holistic_read_state(
            pathlib.Path(child_status["state_path"])
        )
        if (
            evidence.get("collection", {}).get("session_reads") != 1
            or pathlib.Path(str(evidence.get("session"))).resolve()
            != pathlib.Path(candidate["session"]).resolve()
        ):
            raise CreditAnalysisError("batch holistic child collection is invalid")
        item = _batch_item_record(
            candidate,
            child_paths,
            ordinal=ordinal,
            source_fingerprint=child_state["source"]["fingerprint"],
        )
        state["items"].append(item)
        state["candidate_index"] += 1
        _save_batch_state(state)
    if not state["items"]:
        raise CreditAnalysisError("batch selector found no threads with completed model calls")
    manifest = _batch_manifest(state, contract)
    manifest_path = pathlib.Path(state["paths"]["manifest"])
    _write_or_verify_json(manifest_path, manifest, "retained batch manifest")
    state["immutable_artifacts"]["manifest"] = {
        "path": str(manifest_path),
        "sha256": _file_hash(manifest_path),
        "content_hash": _content_hash(manifest),
    }
    state["phase"] = "ready"
    _save_batch_state(state)


def _read_batch_index(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise CreditAnalysisError("batch result index must be a regular file")
    records: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise CreditAnalysisError(
                        f"batch result index has a blank record at line {line_number}"
                    )
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise CreditAnalysisError("batch result index record must be an object")
                records.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CreditAnalysisError(f"batch result index is unreadable: {exc}") from exc
    return records


def _recover_batch_indexed_result(state: dict[str, Any]) -> None:
    """Recover one child result indexed before its atomic batch-state checkpoint."""

    index = _read_batch_index(pathlib.Path(state["paths"]["index"]))
    completed_count = len(state["completed"])
    if len(index) == completed_count:
        return
    if len(index) != completed_count + 1 or completed_count >= len(state["items"]):
        raise CreditAnalysisError("batch result index contains unrecoverable records")
    raw = index[-1]
    if not isinstance(raw, dict):
        raise CreditAnalysisError("batch recovery index record must be an object")
    _closed(raw, {"schema", *BATCH_COMPLETED_FIELDS}, "batch recovery record")
    item = state["items"][completed_count]
    path = _existing_file(raw["path"], "recoverable batch child result")
    expected = {
        "schema": BATCH_INDEX_SCHEMA,
        "ordinal": item["ordinal"],
        "thread_id": item["thread_id"],
        "path": str(path),
        "sha256": _file_hash(path),
        "content_hash": _content_hash(
            _read_json(path, "recoverable batch child result")
        ),
    }
    if raw != expected or path.resolve() != pathlib.Path(
        item["final_result_path"]
    ).resolve():
        raise CreditAnalysisError("recoverable batch result does not match pending thread")
    state["completed"].append({key: raw[key] for key in BATCH_COMPLETED_FIELDS})
    state["current_index"] = completed_count + 1
    _save_batch_state(state)


def _verify_batch_completed(state: Mapping[str, Any]) -> None:
    completed = state.get("completed")
    if not isinstance(completed, list):
        raise CreditAnalysisError("batch completed records must be a list")
    index = _read_batch_index(pathlib.Path(state["paths"]["index"]))
    if len(index) != len(completed):
        raise CreditAnalysisError("batch result index and state counts differ")
    for position, raw in enumerate(completed):
        if not isinstance(raw, dict):
            raise CreditAnalysisError("batch completed record must be an object")
        _closed(raw, BATCH_COMPLETED_FIELDS, "batch completed record")
        item = state["items"][position]
        if raw["ordinal"] != position + 1 or raw["thread_id"] != item["thread_id"]:
            raise CreditAnalysisError("batch completed records are reordered")
        path = _existing_file(raw["path"], "batch child final result")
        if path.resolve() != pathlib.Path(item["final_result_path"]).resolve():
            raise CreditAnalysisError("batch completed result path is invalid")
        if _file_hash(path) != raw["sha256"]:
            raise CreditAnalysisError("batch completed result hash mismatch")
        if _content_hash(_read_json(path, "batch child final result")) != raw[
            "content_hash"
        ]:
            raise CreditAnalysisError("batch completed result content hash mismatch")
        expected_index = {"schema": BATCH_INDEX_SCHEMA, **raw}
        if index[position] != expected_index:
            raise CreditAnalysisError("batch result index record mismatch")


def _batch_finding_id(thread_id: str, finding_id: str) -> str:
    return f"{thread_id}:{finding_id}"


def _batch_child_view(
    result: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Project a validated holistic result onto the stable batch aggregate shape."""

    if (
        result.get("schema") != contract["orchestration_final_schema"]
        or result.get("action") != "full-analysis"
        or result.get("mode") != "full-analysis"
    ):
        raise CreditAnalysisError("batch child holistic result schema changed")
    classifications = result.get("classification_totals")
    if not isinstance(classifications, Mapping):
        raise CreditAnalysisError("batch child classification totals are invalid")
    classification_keys = (
        "necessary",
        "avoidable_implemented",
        "avoidable_unimplemented",
        "reviewed_no_confirmed_waste",
        "unassessed",
    )
    if any(
        not isinstance(classifications.get(key), int)
        or isinstance(classifications.get(key), bool)
        or classifications[key] < 0
        for key in classification_keys
    ):
        raise CreditAnalysisError("batch child classification totals are invalid")
    findings_value = result.get("confirmed_findings")
    risks_value = result.get("plausible_risks")
    decisions_value = result.get("candidate_decisions")
    groups_value = result.get("call_classifications")
    if not isinstance(findings_value, list):
        raise CreditAnalysisError("batch child holistic inventory is invalid")
    if not isinstance(risks_value, list):
        raise CreditAnalysisError("batch child holistic inventory is invalid")
    if not isinstance(decisions_value, list):
        raise CreditAnalysisError("batch child holistic inventory is invalid")
    if not isinstance(groups_value, list):
        raise CreditAnalysisError("batch child holistic inventory is invalid")

    producer_keys: list[tuple[str, str, str]] = []
    for finding in findings_value:
        if not isinstance(finding, Mapping):
            raise CreditAnalysisError("batch child finding is invalid")
        key = (
            str(finding.get("producer_type")),
            str(finding.get("producer_owner")),
            str(finding.get("proposed_durable_control")),
        )
        if key not in producer_keys:
            producer_keys.append(key)
    producer_group_by_key = {
        key: f"holistic-producer-{index:04d}"
        for index, key in enumerate(producer_keys, start=1)
    }
    findings: list[dict[str, Any]] = []
    for rank, raw in enumerate(findings_value, start=1):
        finding = dict(raw)
        surfaces = finding.get("contributing_surfaces")
        if not isinstance(surfaces, list) or not surfaces:
            raise CreditAnalysisError("batch child finding has no contributing surface")
        affected_calls = finding.get("affected_call_ids")
        if not isinstance(affected_calls, list):
            raise CreditAnalysisError("batch child finding calls are invalid")
        observed = finding.get("observed_avoidable_call_count")
        if not isinstance(observed, int) or isinstance(observed, bool) or observed < 0:
            raise CreditAnalysisError("batch child finding count is invalid")
        producer_key = (
            str(finding.get("producer_type")),
            str(finding.get("producer_owner")),
            str(finding.get("proposed_durable_control")),
        )
        findings.append(
            {
                **finding,
                "source_surface": surfaces[0],
                "expected_value_rank": rank,
                "primary_call_ids": (
                    list(affected_calls)
                    if finding.get("waste_kind") == "model-calls"
                    else []
                ),
                "secondary_call_ids": [],
                "deduplicated_avoidable_call_count": observed,
                "producer_group_id": producer_group_by_key[producer_key],
                "roi": {
                    "finding_id": finding.get("id"),
                    "recurrence": finding.get("recurrence"),
                    "one_time_implementation_cost": finding.get(
                        "one_time_implementation_cost"
                    ),
                    "ongoing_complexity": finding.get("complexity"),
                    "confidence": finding.get("confidence"),
                },
            }
        )

    producer_groups = []
    for key in producer_keys:
        producer_type, owner, control = key
        members = [
            finding
            for finding in findings
            if (
                str(finding["producer_type"]),
                str(finding["producer_owner"]),
                str(finding["proposed_durable_control"]),
            )
            == key
        ]
        producer_groups.append(
            {
                "id": producer_group_by_key[key],
                "producer_type": producer_type,
                "owner": owner,
                "finding_ids": [str(finding["id"]) for finding in members],
                "recommended_control": control,
                "targeted_verification": list(
                    dict.fromkeys(
                        check
                        for finding in members
                        for check in finding["targeted_verification"]
                    )
                ),
            }
        )

    primary: list[dict[str, Any]] = []
    necessary: list[dict[str, Any]] = []
    for group in groups_value:
        if not isinstance(group, Mapping) or not isinstance(group.get("call_ids"), list):
            raise CreditAnalysisError("batch child call classification is invalid")
        for call_id in group["call_ids"]:
            mapping = {
                "call_id": call_id,
                "classification": group.get("classification"),
                "reason_code": group.get("reason_code"),
                "reason": group.get("rationale"),
                "evidence_refs": group.get("evidence_refs"),
                "workstream": group.get("workstream"),
            }
            primary.append(mapping)
            if group.get("classification") == "necessary":
                necessary.append(
                    {
                        "call_id": call_id,
                        "reason_code": group.get("reason_code"),
                        "reason": group.get("rationale"),
                    }
                )

    total_calls = sum(int(classifications[key]) for key in classification_keys)
    protocol_overhead = classifications.get("protocol_overhead", 0)
    if not isinstance(protocol_overhead, int) or isinstance(protocol_overhead, bool):
        raise CreditAnalysisError("batch child protocol overhead total is invalid")
    totals = {
        "total_model_calls": total_calls,
        "necessary_calls": classifications["necessary"],
        "protocol_overhead_calls": protocol_overhead,
        "reviewed_no_confirmed_waste_calls": classifications[
            "reviewed_no_confirmed_waste"
        ],
        "unassessed_calls": classifications["unassessed"],
        "avoidable_calls": classifications["avoidable_implemented"]
        + classifications["avoidable_unimplemented"],
        "avoidable_implemented_calls": classifications["avoidable_implemented"],
        "avoidable_unimplemented_calls": classifications[
            "avoidable_unimplemented"
        ],
        "confirmed_findings": len(findings),
        "plausible_risks": len(risks_value),
    }
    return {
        "confirmed_findings": findings,
        "plausible_risks": list(risks_value),
        "dismissals": [
            dict(decision)
            for decision in decisions_value
            if isinstance(decision, Mapping)
            and decision.get("disposition") == "dismissed-candidate"
        ],
        "necessary_call_exclusions": necessary,
        "primary_call_mappings": primary,
        "secondary_call_mappings": [],
        "producer_grouped_recommendations": producer_groups,
        "totals": totals,
        "priced_cost": None,
    }


def _batch_finding_records(
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build compact synthesis input from validated child final results only."""

    findings: list[dict[str, Any]] = []
    thread_totals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item, record in zip(state["items"], state["completed"], strict=True):
        result = _read_json(pathlib.Path(record["path"]), "batch child final result")
        child = _batch_child_view(result, contract)
        thread_totals.append(
            {
                "thread_id": item["thread_id"],
                "thread_name": item["thread_name"],
                "analysis_id": result["analysis_id"],
                "totals": child["totals"],
            }
        )
        for finding in child["confirmed_findings"]:
            batch_finding_id = _batch_finding_id(item["thread_id"], finding["id"])
            if batch_finding_id in seen:
                raise CreditAnalysisError(
                    f"duplicate batch finding identity: {batch_finding_id}"
                )
            seen.add(batch_finding_id)
            findings.append(
                {
                    "batch_finding_id": batch_finding_id,
                    "thread_id": item["thread_id"],
                    "thread_name": item["thread_name"],
                    "analysis_id": result["analysis_id"],
                    "finding_id": finding["id"],
                    "title": finding["title"],
                    "problem_summary": finding["problem_summary"],
                    "waste_kind": finding["waste_kind"],
                    "source_surface": finding["source_surface"],
                    "contributing_surfaces": finding["contributing_surfaces"],
                    "producer_type": finding["producer_type"],
                    "producer_owner": finding["producer_owner"],
                    "proposed_durable_control": finding[
                        "proposed_durable_control"
                    ],
                    "implementation_status": finding["implementation_status"],
                    "deduplicated_avoidable_call_count": finding[
                        "deduplicated_avoidable_call_count"
                    ],
                    "targeted_verification": finding["targeted_verification"],
                    "helper_categories": finding["helper_categories"],
                    "complexity": finding["complexity"],
                    "confidence": finding["confidence"],
                }
            )
    return findings, thread_totals


def _open_batch_summary(
    state: dict[str, Any],
    contract: Mapping[str, Any],
) -> None:
    """Open the one deterministic cross-thread summary pass."""

    if state["phase"] != "ready" or state["current_index"] != len(state["items"]):
        raise CreditAnalysisError("batch summary cannot open before every child")
    if state.get("batch_summary") is not None:
        raise CreditAnalysisError("batch summary is already open")
    findings, thread_totals = _batch_finding_records(state, contract)
    pass_id = f"{state['batch_id']}.batch-summary"
    fingerprint = _content_hash(
        {"batch_id": state["batch_id"], "findings": findings}
    )
    context_path = pathlib.Path(state["paths"]["batch_summary_context"])
    result_path = pathlib.Path(state["paths"]["batch_summary_result"])
    context = {
        "batch_id": state["batch_id"],
        "pass_id": pass_id,
        "finding_fingerprint": fingerprint,
        "findings": findings,
        "thread_totals": thread_totals,
        "result_contract": {
            "fields": list(BATCH_SUMMARY_RESULT_FIELD_ORDER),
            "group_fields": list(BATCH_SUMMARY_GROUP_FIELD_ORDER),
        },
        "artifact_paths": {
            "state": state["paths"]["state"],
            "context": str(context_path),
            "result": str(result_path),
        },
    }
    _write_or_verify_json(context_path, context, "batch summary context")
    state["batch_summary"] = {
        "pass_id": pass_id,
        "finding_fingerprint": fingerprint,
        "finding_ids": [finding["batch_finding_id"] for finding in findings],
        "context_path": str(context_path),
        "result_path": str(result_path),
        "context_sha256": _file_hash(context_path),
        "accepted": None,
    }
    state["phase"] = "batch-summary"


def _validate_batch_summary(
    result: dict[str, Any],
    *,
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate exact finding coverage without trusting model arithmetic."""

    _closed(result, BATCH_SUMMARY_RESULT_FIELDS, "batch summary result")
    pending = state.get("batch_summary")
    if state.get("phase") not in {
        "batch-summary",
        "ready-to-finalize",
        "finalized",
    } or not isinstance(pending, Mapping):
        raise CreditAnalysisError("batch summary is not pending")
    expected = {
        "batch_id": state["batch_id"],
        "pass_id": pending["pass_id"],
        "finding_fingerprint": pending["finding_fingerprint"],
        "artifact_paths": {
            "state": state["paths"]["state"],
            "context": pending["context_path"],
            "result": pending["result_path"],
        },
    }
    for field, value in expected.items():
        if result.get(field) != value:
            raise CreditAnalysisError(
                f"batch summary {field} does not match pending state"
            )
    findings, _ = _batch_finding_records(state, contract)
    finding_by_id = {
        finding["batch_finding_id"]: finding for finding in findings
    }
    if list(finding_by_id) != list(pending["finding_ids"]):
        raise CreditAnalysisError("batch summary finding inventory changed")
    normalized_groups: list[dict[str, Any]] = []
    grouped_findings: list[str] = []
    group_ids: set[str] = set()
    for raw in _objects(result.get("groups"), "batch summary groups"):
        _closed(raw, BATCH_SUMMARY_GROUP_FIELDS, "batch summary group")
        group_id = _identifier(raw.get("id"), "batch summary group id")
        title = raw.get("title")
        producer_type = raw.get("producer_type")
        owner = raw.get("owner")
        finding_ids = _strings(
            raw.get("finding_ids"), f"batch summary group {group_id} findings"
        )
        control = raw.get("recommended_control")
        variants = _strings(
            raw.get("material_variants"),
            f"batch summary group {group_id} variants",
            allow_empty=True,
        )
        confidence = _number(
            raw.get("confidence"), f"batch summary group {group_id} confidence"
        )
        if (
            group_id in group_ids
            or not isinstance(title, str)
            or not title.strip()
            or producer_type not in contract["producer_types"]
            or owner is not None and (not isinstance(owner, str) or not owner.strip())
            or not set(finding_ids).issubset(finding_by_id)
            or not isinstance(control, str)
            or not control.strip()
            or confidence > 1
        ):
            raise CreditAnalysisError(
                f"batch summary group is invalid: {group_id}"
            )
        normalized_owner = owner.strip() if isinstance(owner, str) else None
        if any(
            finding_by_id[finding_id]["producer_type"] != producer_type
            or finding_by_id[finding_id]["producer_owner"] != normalized_owner
            for finding_id in finding_ids
        ):
            raise CreditAnalysisError(
                f"batch summary group mixes producer owners: {group_id}"
            )
        group_ids.add(group_id)
        grouped_findings.extend(finding_ids)
        normalized_groups.append(
            {
                "id": group_id,
                "title": title.strip(),
                "producer_type": producer_type,
                "owner": normalized_owner,
                "finding_ids": finding_ids,
                "recommended_control": control.strip(),
                "material_variants": variants,
                "confidence": confidence,
            }
        )
    if (
        set(grouped_findings) != set(finding_by_id)
        or len(grouped_findings) != len(finding_by_id)
    ):
        raise CreditAnalysisError(
            "batch summary groups must partition every finding exactly once"
        )
    return {**result, "groups": normalized_groups}


def _cleanup_batch_transients(state: Mapping[str, Any]) -> None:
    cleanup = state.get("cleanup")
    expected_path = pathlib.Path(state["paths"]["batch_summary_context"]).resolve()
    if cleanup != {
        "owner": "credit-analysis-workflow",
        "trigger": "successful-finalization",
        "transient_paths": [str(expected_path)],
    }:
        raise CreditAnalysisError("batch cleanup ownership is invalid")
    if expected_path.is_symlink():
        raise CreditAnalysisError("refusing to delete symlinked batch context")
    if expected_path.exists():
        if not expected_path.is_file():
            raise CreditAnalysisError("batch summary context is not a file")
        expected_path.unlink()


def _load_batch_state(
    state_path: pathlib.Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate bounded batch ownership and recover one indexed child result."""

    resolved = _existing_file(str(state_path), "batch state")
    state = _read_json(resolved, "batch state")
    _closed(state, BATCH_STATE_FIELDS, "batch state")
    if (
        state.get("schema") != BATCH_STATE_SCHEMA
        or state.get("version") != BATCH_STATE_VERSION
    ):
        raise CreditAnalysisError("unsupported batch state schema or version")
    if state.get("mutation_authority") is not False:
        raise CreditAnalysisError("batch mutation authority must remain false")
    paths = state.get("paths")
    if not isinstance(paths, dict) or set(paths) != {
        "state",
        "manifest",
        "requests_dir",
        "analyses_dir",
        "evidence_dir",
        "index",
        "batch_summary_context",
        "batch_summary_result",
        "final_result",
    }:
        raise CreditAnalysisError("batch state paths are invalid")
    root = resolved.parent
    expected = {
        "state": root / "batch-state.json",
        "requests_dir": root / "requests",
        "analyses_dir": root / "analyses",
        "evidence_dir": root / "evidence",
        "index": root / "batch-results.jsonl",
        "batch_summary_context": root / "batch-summary-context.json",
        "batch_summary_result": root / "batch-summary.json",
        "final_result": root / "batch-final-machine-result.json",
    }
    for key, path in expected.items():
        if pathlib.Path(paths[key]).resolve() != path.resolve():
            raise CreditAnalysisError(f"batch {key} path escapes controller ownership")
    contract = _load_contract()
    if state["surface_contract_version"] != contract["surface_contract_version"]:
        raise CreditAnalysisError("batch surface contract version is stale")
    if state["source_selection_contract_version"] != contract[
        "source_selection_contract_version"
    ]:
        raise CreditAnalysisError("batch source selection contract is stale")
    artifacts = state.get("immutable_artifacts")
    if not isinstance(artifacts, dict):
        raise CreditAnalysisError("batch immutable artifacts are invalid")
    for label in ("request", "surface_contract"):
        record = artifacts.get(label)
        if not isinstance(record, dict):
            raise CreditAnalysisError(f"batch {label} artifact is invalid")
        path = _existing_file(record.get("path"), f"batch {label} artifact")
        if _file_hash(path) != record.get("sha256"):
            raise CreditAnalysisError(f"batch {label} artifact changed")
    pricing = artifacts.get("pricing_profile")
    if pricing is not None:
        if not isinstance(pricing, dict):
            raise CreditAnalysisError("batch pricing artifact is invalid")
        path = _existing_file(pricing.get("path"), "batch pricing artifact")
        if _file_hash(path) != pricing.get("sha256"):
            raise CreditAnalysisError("batch pricing artifact changed")
    phase = state.get("phase")
    if phase not in {
        "preparing",
        "ready",
        "batch-summary",
        "ready-to-finalize",
        "finalized",
    }:
        raise CreditAnalysisError("batch phase is invalid")
    manifest = artifacts.get("manifest")
    if phase == "preparing":
        if manifest is not None:
            raise CreditAnalysisError("preparing batch must not freeze a manifest")
    else:
        if not isinstance(manifest, dict):
            raise CreditAnalysisError("ready batch lacks an immutable manifest")
        path = _existing_file(manifest.get("path"), "batch manifest")
        if path.resolve() != pathlib.Path(paths["manifest"]).resolve():
            raise CreditAnalysisError("batch manifest path changed")
        if _file_hash(path) != manifest.get("sha256"):
            raise CreditAnalysisError("batch manifest hash mismatch")
    items = state.get("items")
    if not isinstance(items, list):
        raise CreditAnalysisError("batch items must be a list")
    seen_threads: set[str] = set()
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise CreditAnalysisError("batch item must be an object")
        _closed(item, BATCH_ITEM_FIELDS, "batch item")
        if item["ordinal"] != position or item["thread_id"] in seen_threads:
            raise CreditAnalysisError("batch item order or identity is invalid")
        seen_threads.add(item["thread_id"])
        for key in ("request_path", "state_path", "evidence_path"):
            _existing_file(item[key], f"batch item {key}")
    _recover_batch_indexed_result(state)
    current_index = state.get("current_index")
    if (
        not isinstance(current_index, int)
        or isinstance(current_index, bool)
        or current_index < 0
        or current_index > len(items)
    ):
        raise CreditAnalysisError("batch current index is invalid")
    _verify_batch_completed(state)
    if current_index != len(state["completed"]):
        raise CreditAnalysisError("batch current index does not match completed results")
    cleanup = state.get("cleanup")
    summary_context = pathlib.Path(paths["batch_summary_context"]).resolve()
    if cleanup != {
        "owner": "credit-analysis-workflow",
        "trigger": "successful-finalization",
        "transient_paths": [str(summary_context)],
    }:
        raise CreditAnalysisError("batch cleanup contract is invalid")
    if phase == "ready" and current_index == len(items):
        _open_batch_summary(state, contract)
        _save_batch_state(state)
        phase = state["phase"]
    if phase == "ready" and current_index >= len(items):
        raise CreditAnalysisError("ready batch must have one pending thread")
    if phase in {"batch-summary", "ready-to-finalize", "finalized"} and (
        current_index != len(items)
    ):
        raise CreditAnalysisError("batch summary opened before every thread finished")

    summary = state.get("batch_summary")
    if phase in {"preparing", "ready"}:
        if summary is not None:
            raise CreditAnalysisError("batch summary opened before its phase")
    else:
        if not isinstance(summary, dict):
            raise CreditAnalysisError("batch summary state is missing")
        _closed(summary, BATCH_SUMMARY_STATE_FIELDS, "batch summary state")
        expected_pass_id = f"{state['batch_id']}.batch-summary"
        finding_ids = _strings(
            summary.get("finding_ids"),
            "batch summary finding ids",
            allow_empty=True,
        )
        findings, thread_totals = _batch_finding_records(state, contract)
        expected_finding_ids = [item["batch_finding_id"] for item in findings]
        expected_fingerprint = _content_hash(
            {"batch_id": state["batch_id"], "findings": findings}
        )
        expected_context = {
            "batch_id": state["batch_id"],
            "pass_id": expected_pass_id,
            "finding_fingerprint": expected_fingerprint,
            "findings": findings,
            "thread_totals": thread_totals,
            "result_contract": {
                "fields": list(BATCH_SUMMARY_RESULT_FIELD_ORDER),
                "group_fields": list(BATCH_SUMMARY_GROUP_FIELD_ORDER),
            },
            "artifact_paths": {
                "state": paths["state"],
                "context": paths["batch_summary_context"],
                "result": paths["batch_summary_result"],
            },
        }
        if (
            summary.get("pass_id") != expected_pass_id
            or finding_ids != expected_finding_ids
            or summary.get("finding_fingerprint") != expected_fingerprint
            or pathlib.Path(str(summary.get("context_path"))).resolve()
            != summary_context
            or pathlib.Path(str(summary.get("result_path"))).resolve()
            != pathlib.Path(paths["batch_summary_result"]).resolve()
        ):
            raise CreditAnalysisError("batch summary state identity is invalid")
        if phase != "finalized" or summary_context.exists():
            context = _existing_file(
                summary.get("context_path"), "batch summary context"
            )
            if (
                _file_hash(context) != summary.get("context_sha256")
                or _content_hash(_read_json(context, "batch summary context"))
                != _content_hash(expected_context)
            ):
                raise CreditAnalysisError("batch summary context changed")
        accepted = summary.get("accepted")
        if phase == "batch-summary":
            if accepted is not None:
                raise CreditAnalysisError("pending batch summary is already accepted")
        else:
            if not isinstance(accepted, dict):
                raise CreditAnalysisError("accepted batch summary is missing")
            _closed(
                accepted,
                BATCH_SUMMARY_ACCEPTED_FIELDS,
                "accepted batch summary",
            )
            result = _existing_file(accepted.get("path"), "batch summary result")
            payload = _validate_batch_summary(
                _read_json(result, "batch summary result"),
                state=state,
                contract=contract,
            )
            if (
                result.resolve()
                != pathlib.Path(paths["batch_summary_result"]).resolve()
                or _file_hash(result) != accepted.get("sha256")
                or _content_hash(payload) != accepted.get("content_hash")
            ):
                raise CreditAnalysisError("accepted batch summary changed")

    finalized = state.get("finalized")
    if not isinstance(finalized, bool) or finalized != (phase == "finalized"):
        raise CreditAnalysisError("batch finalized status disagrees with its phase")
    if finalized:
        final = state.get("final_result")
        if not isinstance(final, dict):
            raise CreditAnalysisError("finalized batch state is incomplete")
        _closed(final, {"path", "sha256", "content_hash"}, "batch final result")
        final_path = _existing_file(final.get("path"), "batch final result")
        final_payload = _read_json(final_path, "batch final result")
        if (
            final_path.resolve() != pathlib.Path(paths["final_result"]).resolve()
            or _file_hash(final_path) != final.get("sha256")
            or _content_hash(final_payload) != final.get("content_hash")
        ):
            raise CreditAnalysisError("batch final result hash mismatch")
        _cleanup_batch_transients(state)
    elif state.get("final_result") is not None:
        raise CreditAnalysisError("unfinished batch records a final result")
    return state, contract


def _batch_public_status(
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    if state["finalized"] is True:
        return {
            "batch_id": state["batch_id"],
            "complete": True,
            "selected_threads": len(state["items"]),
            "batch_state_path": state["paths"]["state"],
            "manifest_path": state["paths"]["manifest"],
            "batch_summary_result_path": state["batch_summary"]["result_path"],
            "final_result_path": state["final_result"]["path"],
        }
    common = {
        "batch_id": state["batch_id"],
        "selected_threads": len(state["items"]),
        "batch_state_path": state["paths"]["state"],
        "manifest_path": state["paths"]["manifest"],
    }
    if state["phase"] == "preparing":
        return {**common, "preparing": True, "resume_with": "prepare-batch"}
    if state["phase"] == "batch-summary":
        summary = state["batch_summary"]
        return {
            **common,
            "pending_phase": "batch-summary",
            "pass_id": summary["pass_id"],
            "context_path": summary["context_path"],
            "required_result_path": summary["result_path"],
        }
    if state["phase"] == "ready-to-finalize":
        return {
            **common,
            "ready_to_finalize": True,
            "batch_summary_result_path": state["batch_summary"]["result_path"],
        }
    item = state["items"][state["current_index"]]
    child_status = _holistic_controller().command_orchestration_status(
        pathlib.Path(item["state_path"])
    )
    return {
        **common,
        "current_ordinal": item["ordinal"],
        "pending_thread_id": item["thread_id"],
        "pending_thread_name": item["thread_name"],
        "child_request_path": item["request_path"],
        "child_state_path": item["state_path"],
        "child_status": child_status,
    }


def command_prepare_batch(request_path: pathlib.Path) -> dict[str, Any]:
    """Freeze and prepare one resumable per-thread batch from an exact request."""

    raw = _read_json(request_path, "batch request")
    _closed(raw, BATCH_REQUEST_FIELDS, "batch request")
    task_root, paths = _batch_request_paths(raw)
    state_path = paths["state"]
    if state_path.exists():
        state, contract = _load_batch_state(state_path)
        request_record = state["immutable_artifacts"]["request"]
        if pathlib.Path(request_record["path"]).resolve() != request_path.resolve():
            raise CreditAnalysisError("batch request path does not match resumable state")
        if _file_hash(request_path) != request_record["sha256"]:
            raise CreditAnalysisError("batch request changed during resume")
        if state["phase"] == "preparing":
            _resume_batch_preparation(state, contract)
        return _batch_public_status(state, contract)
    contract = _load_contract()
    ledger = _load_ledger()
    request = _validated_batch_request(request_path, contract, ledger)
    index, candidates, exclusions = _select_batch_candidates(request, ledger)
    for key in ("requests_dir", "analyses_dir", "evidence_dir"):
        request["paths"][key].mkdir()
    state = {
        "schema": BATCH_STATE_SCHEMA,
        "version": BATCH_STATE_VERSION,
        "batch_id": secrets.token_hex(12),
        "phase": "preparing",
        "action": "full-analysis",
        "mode": "per-thread-batch",
        "mutation_authority": False,
        "surface_contract_version": contract["surface_contract_version"],
        "source_selection_contract_version": contract[
            "source_selection_contract_version"
        ],
        "selector": request["selector"],
        "as_of": request["as_of"].isoformat().replace("+00:00", "Z"),
        "source_index": {
            "path": index["path"],
            "fingerprint": index["fingerprint"],
        },
        "candidates": candidates,
        "candidate_index": 0,
        "items": [],
        "exclusions": exclusions,
        "current_index": 0,
        "completed": [],
        "batch_summary": None,
        "paths": {key: str(value) for key, value in request["paths"].items()},
        "immutable_artifacts": {
            "request": {
                "path": str(request_path),
                "sha256": request["request_hash"],
            },
            "surface_contract": {
                "path": str(CONTRACT_PATH),
                "sha256": _file_hash(CONTRACT_PATH),
            },
            "manifest": None,
            "pricing_profile": (
                {
                    "path": str(request["pricing"]),
                    "sha256": _file_hash(request["pricing"]),
                }
                if request["pricing"] is not None
                else None
            ),
        },
        "cleanup": {
            "owner": "credit-analysis-workflow",
            "trigger": "successful-finalization",
            "transient_paths": [
                str(request["paths"]["batch_summary_context"].resolve())
            ],
        },
        "finalized": False,
        "final_result": None,
    }
    _exclusive_json(state_path, state, "batch state")
    _resume_batch_preparation(state, contract)
    return _batch_public_status(state, contract)


def command_status_batch(state_path: pathlib.Path) -> dict[str, Any]:
    state, contract = _load_batch_state(state_path)
    return _batch_public_status(state, contract)


def command_advance_batch(
    state_path: pathlib.Path,
    result_path: pathlib.Path,
) -> dict[str, Any]:
    """Accept the exact pending child or batch-summary result."""

    state, contract = _load_batch_state(state_path)
    result = _existing_file(str(result_path), "batch child final result")
    if state["completed"]:
        previous = state["completed"][-1]
        if result.resolve() == pathlib.Path(previous["path"]).resolve():
            if _file_hash(result) != previous["sha256"]:
                raise CreditAnalysisError("conflicting batch result resubmission")
            return _batch_public_status(state, contract)
    summary = state.get("batch_summary")
    if isinstance(summary, dict) and summary.get("accepted") is not None:
        accepted = summary["accepted"]
        if result.resolve() == pathlib.Path(accepted["path"]).resolve():
            if _file_hash(result) != accepted["sha256"]:
                raise CreditAnalysisError(
                    "conflicting batch summary resubmission"
                )
            return _batch_public_status(state, contract)
    if state["phase"] == "batch-summary":
        if not isinstance(summary, dict):
            raise CreditAnalysisError("batch summary state is missing")
        if result.resolve() != pathlib.Path(summary["result_path"]).resolve():
            raise CreditAnalysisError("result is not the pending batch summary")
        payload = _validate_batch_summary(
            _read_json(result, "batch summary result"),
            state=state,
            contract=contract,
        )
        summary["accepted"] = {
            "path": str(result),
            "sha256": _file_hash(result),
            "content_hash": _content_hash(payload),
        }
        state["phase"] = "ready-to-finalize"
        _save_batch_state(state)
        return _batch_public_status(state, contract)
    if state["phase"] != "ready" or state["current_index"] >= len(state["items"]):
        raise CreditAnalysisError("batch has no pending result")
    item = state["items"][state["current_index"]]
    if result.resolve() != pathlib.Path(item["final_result_path"]).resolve():
        raise CreditAnalysisError("batch result is not for the exact pending thread")
    child_state, _, _, _ = _holistic_controller()._holistic_read_state(
        pathlib.Path(item["state_path"])
    )
    if child_state["phase"] != "complete":
        raise CreditAnalysisError("pending thread holistic analysis is not complete")
    payload = _read_json(result, "batch child final result")
    if (
        payload.get("schema") != contract["orchestration_final_schema"]
        or payload.get("mode") != "full-analysis"
        or child_state["source"].get("value") != item["thread_id"]
    ):
        raise CreditAnalysisError("batch child final result identity is invalid")
    record = {
        "ordinal": item["ordinal"],
        "thread_id": item["thread_id"],
        "path": str(result),
        "sha256": _file_hash(result),
        "content_hash": _content_hash(payload),
    }
    _append_index(
        pathlib.Path(state["paths"]["index"]),
        {"schema": BATCH_INDEX_SCHEMA, **record},
    )
    state["completed"].append(record)
    state["current_index"] += 1
    if state["current_index"] == len(state["items"]):
        _open_batch_summary(state, contract)
    _save_batch_state(state)
    return _batch_public_status(state, contract)


def _build_batch_final(
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Group findings for presentation without changing per-thread accounting."""

    thread_results: list[dict[str, Any]] = []
    thread_totals: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    finding_by_batch_id: dict[str, dict[str, Any]] = {}
    risks: list[dict[str, Any]] = []
    dismissals: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    primary: list[dict[str, Any]] = []
    secondary: list[dict[str, Any]] = []
    producer_groups: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()
    priced_totals: defaultdict[str, float] = defaultdict(float)
    pricing_complete = True
    for item, record in zip(state["items"], state["completed"], strict=True):
        result = _read_json(pathlib.Path(record["path"]), "batch child final result")
        child = _batch_child_view(result, contract)
        identity = {
            "thread_id": item["thread_id"],
            "thread_name": item["thread_name"],
            "analysis_id": result["analysis_id"],
        }
        thread_results.append({**identity, "path": record["path"], "result": result})
        thread_totals.append({**identity, "totals": child["totals"]})
        for value in child["confirmed_findings"]:
            batch_finding_id = _batch_finding_id(item["thread_id"], value["id"])
            if batch_finding_id in finding_by_batch_id:
                raise CreditAnalysisError(
                    f"duplicate batch finding identity: {batch_finding_id}"
                )
            entry = {
                **identity,
                "batch_finding_id": batch_finding_id,
                "finding": value,
            }
            finding_by_batch_id[batch_finding_id] = entry
            findings.append(entry)
        risks.extend({**identity, "risk": value} for value in child["plausible_risks"])
        dismissals.extend({**identity, "dismissal": value} for value in child["dismissals"])
        exclusions.extend(
            {**identity, "exclusion": value}
            for value in child["necessary_call_exclusions"]
        )
        primary.extend(
            {**identity, "mapping": value}
            for value in child["primary_call_mappings"]
        )
        secondary.extend(
            {**identity, "mapping": value}
            for value in child["secondary_call_mappings"]
        )
        producer_groups.extend(
            {**identity, "group": value}
            for value in child["producer_grouped_recommendations"]
        )
        for key, value in child["totals"].items():
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] += value
        priced = child.get("priced_cost")
        if not isinstance(priced, Mapping):
            pricing_complete = False
        else:
            for key, value in priced.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    priced_totals[key] += float(value)

    summary_state = state.get("batch_summary")
    if not isinstance(summary_state, Mapping) or not isinstance(
        summary_state.get("accepted"), Mapping
    ):
        raise CreditAnalysisError("batch summary is not accepted")
    summary_path = _existing_file(
        summary_state["accepted"].get("path"), "accepted batch summary"
    )
    summary = _validate_batch_summary(
        _read_json(summary_path, "accepted batch summary"),
        state=state,
        contract=contract,
    )
    surface_rank = {
        surface_id: rank
        for rank, surface_id in enumerate(contract["surface_order"])
    }
    helper_rank = {
        category: rank
        for rank, category in enumerate(contract["helper_categories"])
    }
    status_rank = {
        status: rank
        for rank, status in enumerate(contract["implementation_statuses"])
    }
    summary_groups: list[dict[str, Any]] = []
    for rank, group in enumerate(summary["groups"], start=1):
        members = [finding_by_batch_id[value] for value in group["finding_ids"]]
        affected_calls: list[dict[str, str]] = []
        seen_calls: set[tuple[str, str]] = set()
        for member in members:
            for call_id in member["finding"]["primary_call_ids"]:
                key = (member["thread_id"], call_id)
                if key not in seen_calls:
                    seen_calls.add(key)
                    affected_calls.append(
                        {"thread_id": member["thread_id"], "call_id": call_id}
                    )
        summary_groups.append(
            {
                "id": group["id"],
                "title": group["title"],
                "expected_value_rank": rank,
                "producer_type": group["producer_type"],
                "owner": group["owner"],
                "recommended_control": group["recommended_control"],
                "material_variants": group["material_variants"],
                "confidence": group["confidence"],
                "findings": [
                    {
                        "batch_finding_id": member["batch_finding_id"],
                        "thread_id": member["thread_id"],
                        "thread_name": member["thread_name"],
                        "analysis_id": member["analysis_id"],
                        "finding_id": member["finding"]["id"],
                        "title": member["finding"]["title"],
                        "source_surface": member["finding"]["source_surface"],
                        "contributing_surfaces": member["finding"][
                            "contributing_surfaces"
                        ],
                    }
                    for member in members
                ],
                "threads": list(
                    dict.fromkeys(member["thread_id"] for member in members)
                ),
                "contributing_surfaces": sorted(
                    {
                        surface
                        for member in members
                        for surface in member["finding"]["contributing_surfaces"]
                    },
                    key=lambda value: surface_rank[value],
                ),
                "helper_categories": sorted(
                    {
                        category
                        for member in members
                        for category in member["finding"]["helper_categories"]
                    },
                    key=lambda value: helper_rank[value],
                ),
                "implementation_statuses": sorted(
                    {
                        member["finding"]["implementation_status"]
                        for member in members
                    },
                    key=lambda value: status_rank[value],
                ),
                "targeted_verification": [
                    {
                        "batch_finding_id": member["batch_finding_id"],
                        "checks": member["finding"]["targeted_verification"],
                    }
                    for member in members
                ],
                "affected_calls": affected_calls,
                "deduplicated_avoidable_call_count": len(affected_calls),
            }
        )
    return {
        "batch_id": state["batch_id"],
        "mode": "per-thread-batch",
        "scope_limitation": (
            "Similar findings are grouped only for presentation; each thread's "
            "findings, classifications, and savings totals remain independent."
        ),
        "selector": state["selector"],
        "as_of": state["as_of"],
        "source_index": state["source_index"],
        "selection_exclusions": state["exclusions"],
        "thread_results": thread_results,
        "per_thread_totals": thread_totals,
        "summary_groups": summary_groups,
        "confirmed_findings": findings,
        "plausible_risks": risks,
        "dismissals": dismissals,
        "necessary_call_exclusions": exclusions,
        "primary_call_mappings": primary,
        "secondary_call_mappings": secondary,
        "producer_grouped_recommendations": producer_groups,
        "totals": {
            "analyzed_threads": len(state["items"]),
            "session_collections": len(state["items"]),
            **dict(sorted(totals.items())),
        },
        "priced_cost": (
            {key: round(value, 12) for key, value in sorted(priced_totals.items())}
            if pricing_complete
            else None
        ),
        "retained_paths": {
            "manifest": state["paths"]["manifest"],
            "batch_state": state["paths"]["state"],
            "batch_index": state["paths"]["index"],
            "batch_summary_result": str(summary_path),
            "child_final_results": [record["path"] for record in state["completed"]],
            "batch_final_machine_result": state["paths"]["final_result"],
        },
    }


def command_finalize_batch(state_path: pathlib.Path) -> None:
    """Verify synthesis and retain one complete grouped batch result."""

    state, contract = _load_batch_state(state_path)
    if state["finalized"]:
        return
    if state["phase"] != "ready-to-finalize":
        raise CreditAnalysisError("batch summary is not accepted")
    _verify_batch_completed(state)
    final = _build_batch_final(state, contract)
    path = pathlib.Path(state["paths"]["final_result"])
    sha256 = _write_final_result(path, final)
    state["phase"] = "finalized"
    state["finalized"] = True
    state["final_result"] = {
        "path": str(path),
        "sha256": sha256,
        "content_hash": _content_hash(final),
    }
    _save_batch_state(state)
    _cleanup_batch_transients(state)

__all__ = (
    "_batch_finding_id",
    "_batch_finding_records",
    "_batch_item_paths",
    "_batch_item_record",
    "_batch_manifest",
    "_batch_public_status",
    "_batch_request_paths",
    "_build_batch_final",
    "_cleanup_batch_transients",
    "_load_batch_state",
    "_open_batch_summary",
    "_project_matches",
    "_project_selector",
    "_read_batch_index",
    "_recover_batch_indexed_result",
    "_recover_prepared_batch_item",
    "_resume_batch_preparation",
    "_save_batch_state",
    "_select_batch_candidates",
    "_validate_batch_summary",
    "_validated_batch_request",
    "_verify_batch_completed",
    "_write_or_verify_json",
    "command_advance_batch",
    "command_finalize_batch",
    "command_prepare_batch",
    "command_status_batch",
)
