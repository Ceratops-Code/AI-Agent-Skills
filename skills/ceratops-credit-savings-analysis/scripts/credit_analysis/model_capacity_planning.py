"""Pure capacity planning for the holistic credit-analysis controller.

This module owns byte-bounded run partitioning, Luna admission priority,
flexible Luna result allowances, Sol review capacity, invocation limits, and
retry eligibility. It never reads sessions, launches models, or mutates
controller state. Calls remain
attached to their source run; transport parts are an input-capacity mechanism,
not independent semantic runs.
"""
# ruff: noqa: I001

from __future__ import annotations

from collections.abc import Callable

from .single_thread_analysis import *


# Sol also has to classify source calls. Saved 38-57-candidate reviews with
# 130-151 calls exceeded output capacity, so the count cap remains a heuristic
# alongside input-byte planning rather than a guarantee of a complete result.
SOL_REVIEW_CANDIDATE_BUDGET = 30


def _capacity_json_bytes(value: Any) -> int:
    """Return the exact compact UTF-8 JSON size used by model inputs."""

    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def _capacity_episode_for_calls(
    episode: Mapping[str, Any], calls: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Retain only the run messages referenced by one ordered call group."""

    message_ids = {
        str(message_id)
        for call in calls
        for message_id in call.get("user_message_ids", [])
    }
    return {
        **episode,
        "candidate_ids": [str(call["candidate_id"]) for call in calls],
        "user_messages": [
            message
            for message in episode.get("user_messages", [])
            if str(message.get("message_id")) in message_ids
        ],
        "calls": [dict(call) for call in calls],
    }


def partition_luna_inputs(
    *,
    analysis_id: str,
    episodes: Sequence[Mapping[str, Any]],
    bundle: Mapping[str, Any],
    budget_bytes: int,
    payload_builder: Callable[..., Mapping[str, Any]],
    record_fitter: Callable[[Mapping[str, Any], int], Mapping[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Divide oversized runs into the minimum fitting ordered input parts.

    A normal run remains one part.  An oversized run is split only between its
    ordered call records.  If one complete compact record is still oversized,
    ``record_fitter`` deterministically reduces that record's evidence detail
    while preserving its run, call, candidate, and evidence identities.
    """

    fragments: list[dict[str, Any]] = []

    def payload_for(fragment: Mapping[str, Any]) -> Mapping[str, Any]:
        return payload_builder(
            analysis_id=analysis_id,
            task_id="luna.discovery.0001",
            ordinal=1,
            episodes=[fragment],
            bundle=bundle,
        )

    for source_episode in episodes:
        # Include the largest possible part counters while measuring.  The final
        # counters can only be the same size or smaller, so metadata added after
        # partitioning cannot turn an admitted part into an overflow.
        maximum_part_index = max(1, len(source_episode.get("calls", [])))
        episode = {
            **source_episode,
            "episode_fragment": maximum_part_index,
            "episode_fragment_count": maximum_part_index,
            "run_window_ordinal": maximum_part_index,
            "run_window_count": maximum_part_index,
        }
        if _capacity_json_bytes(payload_for(episode)) <= budget_bytes:
            fragments.append(episode)
            continue
        current: list[Mapping[str, Any]] = []
        for source_call in episode["calls"]:
            call = dict(source_call)
            proposed = _capacity_episode_for_calls(episode, [*current, call])
            if current and _capacity_json_bytes(payload_for(proposed)) > budget_bytes:
                fragments.append(_capacity_episode_for_calls(episode, current))
                current = [call]
            else:
                current = [*current, call]
            singleton = _capacity_episode_for_calls(episode, current)
            if len(current) == 1 and _capacity_json_bytes(payload_for(singleton)) > budget_bytes:
                fitted = dict(record_fitter(call, budget_bytes))
                singleton = _capacity_episode_for_calls(episode, [fitted])
                if _capacity_json_bytes(payload_for(singleton)) > budget_bytes:
                    raise CreditAnalysisError(
                        "one reduced run part exceeds Luna's proven input envelope"
                    )
                current = [fitted]
        if current:
            fragments.append(_capacity_episode_for_calls(episode, current))

    counts = Counter(str(fragment["turn_id"]) for fragment in fragments)
    seen: Counter[str] = Counter()
    normalized: list[dict[str, Any]] = []
    for fragment in fragments:
        turn_id = str(fragment["turn_id"])
        seen[turn_id] += 1
        normalized.append(
            {
                **fragment,
                "episode_fragment": seen[turn_id],
                "episode_fragment_count": counts[turn_id],
                "run_window_ordinal": seen[turn_id],
                "run_window_count": counts[turn_id],
            }
        )
    packets = [[fragment] for fragment in normalized]
    if not packets:
        raise CreditAnalysisError("holistic Luna plan is empty")
    observed = [
        candidate
        for packet in packets
        for episode in packet
        for candidate in episode["candidate_ids"]
    ]
    expected = list(bundle["candidate_ids"])
    if observed != expected or len(observed) != len(set(observed)):
        raise CreditAnalysisError("holistic Luna run-part plan changed call coverage")
    if any(
        _capacity_json_bytes(payload_for(packet[0])) > budget_bytes
        for packet in packets
    ):
        raise CreditAnalysisError("holistic Luna run-part plan exceeds capacity")
    return packets


def select_luna_tasks(
    tasks: Sequence[Mapping[str, Any]], *, maximum_attempts: int
) -> set[str]:
    """Select fitting run parts by largest-run/immediate-successor priority."""

    fitting = [dict(task) for task in tasks if not task.get("capacity_omitted", False)]
    if len(fitting) <= maximum_attempts:
        return {str(task["task_id"]) for task in fitting}
    tasks_by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    run_order: list[str] = []
    for task in fitting:
        turn_id = str(task["turn_id"])
        if turn_id not in tasks_by_run:
            run_order.append(turn_id)
        tasks_by_run[turn_id].append(task)
    for run_tasks in tasks_by_run.values():
        run_tasks.sort(key=lambda task: int(task["run_window_ordinal"]))
    ranked_runs = sorted(
        run_order,
        key=lambda turn_id: (
            -sum(int(task.get("evidence_bytes") or task["input_bytes"]) for task in tasks_by_run[turn_id]),
            run_order.index(turn_id),
        ),
    )
    priority: list[dict[str, Any]] = []
    queued: set[str] = set()
    for anchor in ranked_runs:
        anchor_index = run_order.index(anchor)
        bundle_runs = [anchor]
        if anchor_index + 1 < len(run_order):
            bundle_runs.append(run_order[anchor_index + 1])
        for turn_id in bundle_runs:
            first = tasks_by_run[turn_id][0]
            if str(first["task_id"]) not in queued:
                priority.append(first)
                queued.add(str(first["task_id"]))
        for turn_id in bundle_runs:
            for task in tasks_by_run[turn_id][1:]:
                task_id = str(task["task_id"])
                if task_id not in queued:
                    priority.append(task)
                    queued.add(task_id)
    for task in fitting:
        task_id = str(task["task_id"])
        if task_id not in queued:
            priority.append(task)
            queued.add(task_id)
    return {
        str(task["task_id"])
        for task in priority[:maximum_attempts]
    }


def _exact_reviewer_bins(
    groups: Sequence[Mapping[str, Any]],
    *,
    bin_count: int,
    capacity_bytes: int,
    minimum_output_bytes: int,
    maximum_groups_per_bin: int,
) -> list[list[dict[str, Any]]]:
    """Find a complete packing, using exact search only when best-fit fails."""

    ordered = sorted(
        (dict(group) for group in groups),
        key=lambda group: (
            -int(group["inventory_bytes"]),
            int(group["run_ordinal"]),
            int(group["run_window_ordinal"]),
        ),
    )
    sizes = [
        int(group["inventory_bytes"])
        + int(group.get("framing_bytes") or 0)
        + minimum_output_bytes
        for group in ordered
    ]
    if any(size > capacity_bytes for size in sizes):
        raise CreditAnalysisError(
            "one Luna report cannot fit the proven Sol reviewer envelope"
        )
    if len(ordered) > bin_count * maximum_groups_per_bin:
        raise CreditAnalysisError(
            "Luna parts exceed the fixed Sol candidate budget"
        )
    if sum(sizes) > bin_count * capacity_bytes:
        raise CreditAnalysisError(
            "accepted Luna reports cannot fit the proven Sol reviewer envelope"
        )

    def greedy() -> list[list[int]] | None:
        bins: list[list[int]] = [[] for _ in range(bin_count)]
        loads = [0] * bin_count
        for item_index, size in enumerate(sizes):
            choices = [
                index
                for index in range(bin_count)
                if loads[index] + size <= capacity_bytes
                and len(bins[index]) < maximum_groups_per_bin
            ]
            if not choices:
                return None
            selected = min(choices, key=lambda index: (loads[index], index))
            bins[selected].append(item_index)
            loads[selected] += size
        return bins

    assigned = greedy()
    if assigned is None:
        bins: list[list[int]] = [[] for _ in range(bin_count)]
        loads = [0] * bin_count
        failed: set[tuple[int, tuple[tuple[int, int], ...]]] = set()

        def search(item_index: int) -> bool:
            if item_index == len(ordered):
                return True
            state = (
                item_index,
                tuple(sorted((load, len(bins[index])) for index, load in enumerate(loads))),
            )
            if state in failed:
                return False
            size = sizes[item_index]
            choices = sorted(
                range(bin_count),
                key=lambda index: (-loads[index], index),
            )
            seen_loads: set[tuple[int, int]] = set()
            for selected in choices:
                load = loads[selected]
                bin_state = (load, len(bins[selected]))
                if (
                    bin_state in seen_loads
                    or load + size > capacity_bytes
                    or len(bins[selected]) >= maximum_groups_per_bin
                ):
                    continue
                seen_loads.add(bin_state)
                bins[selected].append(item_index)
                loads[selected] += size
                if search(item_index + 1):
                    return True
                loads[selected] -= size
                bins[selected].pop()
            failed.add(state)
            return False

        if not search(0):
            raise CreditAnalysisError(
                "accepted Luna reports cannot fit the proven Sol reviewer envelope"
            )
        assigned = bins

    return [[ordered[index] for index in group_bin] for group_bin in assigned]


def plan_luna_reviewers(
    groups: Sequence[Mapping[str, Any]],
    *,
    bin_count: int,
    capacity_bytes: int,
    per_report_framing_bytes: int = 1_000,
    minimum_output_bytes: int = 1_000,
    maximum_output_bytes: int = 64_000,
) -> list[list[dict[str, Any]]]:
    """Preassign Luna tasks and prove every reviewer's maximum input fits.

    Fixed inventory and framing are packed first. Each task on one reviewer then
    receives the same flexible allowance from that reviewer's exact remainder.
    Actual Luna reports may be smaller but are never repacked after execution.
    Candidate limits divide one conservative review budget before Luna launches.
    """

    if not groups or bin_count < 1 or capacity_bytes < 1:
        raise CreditAnalysisError("Luna reviewer planning requires admitted tasks")
    if not 0 < minimum_output_bytes <= maximum_output_bytes:
        raise CreditAnalysisError("Luna output allowance bounds are invalid")
    prepared = [
        {**dict(group), "framing_bytes": per_report_framing_bytes}
        for group in groups
    ]
    bins = [
        group_bin
        for group_bin in _exact_reviewer_bins(
            prepared,
            bin_count=min(bin_count, len(prepared)),
            capacity_bytes=capacity_bytes,
            minimum_output_bytes=minimum_output_bytes,
            maximum_groups_per_bin=SOL_REVIEW_CANDIDATE_BUDGET,
        )
        if group_bin
    ]
    planned: list[list[dict[str, Any]]] = []
    for reviewer_index, group_bin in enumerate(bins, start=1):
        group_bin.sort(
            key=lambda group: (
                int(group["run_ordinal"]),
                int(group["run_window_ordinal"]),
            )
        )
        # One slot per Luna part is guaranteed by the count-bounded packing.
        candidate_budget = SOL_REVIEW_CANDIDATE_BUDGET
        per_task, remainder = divmod(candidate_budget, len(group_bin))
        fixed_bytes = sum(
            int(group["inventory_bytes"]) + int(group["framing_bytes"])
            for group in group_bin
        )
        allowance = min(
            maximum_output_bytes,
            (capacity_bytes - fixed_bytes) // len(group_bin),
        )
        if allowance < minimum_output_bytes:
            raise CreditAnalysisError(
                "accepted Luna reports cannot fit the proven Sol reviewer envelope"
            )
        enriched = [
            {
                **group,
                "reviewer_ordinal": reviewer_index,
                "output_byte_limit": allowance,
                "candidate_limit": per_task + int(index < remainder),
                "planned_routing_bytes": (
                    int(group["inventory_bytes"])
                    + int(group["framing_bytes"])
                    + allowance
                ),
            }
            for index, group in enumerate(group_bin)
        ]
        if (
            sum(int(group["planned_routing_bytes"]) for group in enriched)
            > capacity_bytes
        ):
            raise CreditAnalysisError("Sol reviewer capacity proof failed")
        planned.append(enriched)
    return planned


def _sol_validation_error_count(execution: Mapping[str, Any]) -> int:
    """Count rejected semantic results without treating runner failures as data."""

    return sum(
        attempt.get("outcome") == "validation-error"
        for attempt in execution["attempts"]
    )


def _sol_attempt_capacity(
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
    task: Mapping[str, Any],
) -> int:
    """Return launchable Sol attempts while preserving the dependent final slot."""

    maximum = int(contract["semantic_call_contract"]["sol_max_attempts"])
    reserve_final = int(
        task["phase"] != "sol-final"
        and state["execution"]["sol.final"]["status"] == "pending"
    )
    return max(
        0,
        maximum - int(state["model_attempts"]["sol"]) - reserve_final,
    )


def _can_retry_sol_validation(
    state: Mapping[str, Any],
    contract: Mapping[str, Any],
    task: Mapping[str, Any],
) -> bool:
    """Allow one task-local correction only inside the global Sol attempt cap."""

    execution = state["execution"][task["task_id"]]
    rejected = _sol_validation_error_count(execution)
    retry_limit = int(
        contract["semantic_call_contract"][
            "sol_max_validation_retries_per_task"
        ]
    )
    return 0 < rejected <= retry_limit and _sol_attempt_capacity(
        state, contract, task
    ) > 0


def _validate_sol_call_budget(
    state: Mapping[str, Any], contract: Mapping[str, Any]
) -> None:
    """Reject oversized plans and counters that disagree with actual invocations.

    Retries belong to their frozen task and never consume a new planned slot.
    Launch failures with model_invoked=False do not consume invocation budget.
    This read-only check also applies to completed state and retained recovery.
    """

    limits = contract["semantic_call_contract"]
    tasks = state["manifest"]["sol_tasks"]
    if len(tasks) > int(limits["sol_max_planned_calls"]):
        raise CreditAnalysisError("Sol planned-call cap was exceeded")
    attempts = [
        attempt
        for task in tasks
        for attempt in state["execution"][task["task_id"]]["attempts"]
    ]
    if any(not isinstance(attempt.get("model_invoked"), bool) for attempt in attempts):
        raise CreditAnalysisError("Sol invocation accounting is invalid")
    actual = state["model_attempts"]["sol"]
    if not isinstance(actual, int) or isinstance(actual, bool) or actual < 0:
        raise CreditAnalysisError("Sol invocation count is invalid")
    if actual > int(limits["sol_max_attempts"]):
        raise CreditAnalysisError("Sol attempt cap was exceeded")
    if actual != sum(attempt["model_invoked"] for attempt in attempts):
        raise CreditAnalysisError("Sol invocation count disagrees with retained attempts")


__all__ = (
    "SOL_REVIEW_CANDIDATE_BUDGET",
    "_can_retry_sol_validation",
    "_sol_attempt_capacity",
    "_sol_validation_error_count",
    "_validate_sol_call_budget",
    "partition_luna_inputs",
    "plan_luna_reviewers",
    "select_luna_tasks",
)
