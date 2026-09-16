"""Pure report bookkeeping over validated semantic decisions.

The controller owns evidence, model judgments, and persistence. These helpers
validate result shapes, order surface sets, reconcile temporary-control links,
and preserve reviewer records without performing I/O or adjudicating findings.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from .single_thread_analysis import CreditAnalysisError


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


def _holistic_temporary_control_merges(
    raw_merges: Any,
    *,
    review_by_id: Mapping[str, Mapping[str, Any]],
    finding_by_id: Mapping[str, Mapping[str, Any]],
    surface_order: Sequence[str],
) -> list[dict[str, Any]]:
    """Complete report links without changing validated review decisions.

    Explicit links must pass validation before missing links are filled. A
    finding with missing links must have one exact review owner and at most
    one existing merge; otherwise choosing a merge would require judgment.
    New control keys reuse the linked finding's durable control verbatim.
    Neither the raw report nor its review/finding records are mutated.
    """

    raw_merges = _result_objects(
        raw_merges, "temporary-control merges"
    )
    merges: list[dict[str, Any]] = []
    merged_reviews: set[str] = set()
    merge_keys: set[tuple[str, str]] = set()
    required_merged = {
        review_id for review_id, review in review_by_id.items()
        if review["finding_id"] is not None
    }
    for review_id in sorted(required_merged):
        owner = review_by_id[review_id].get("owning_producer")
        if not isinstance(owner, str) or not owner.strip():
            raise CreditAnalysisError(
                f"temporary-control review {review_id} owner is invalid"
            )
    for index, merge in enumerate(raw_merges, start=1):
        label = f"temporary-control merge {index}"
        _closed_result(
            merge,
            {"control_key", "owning_producer", "review_ids", "contributing_surfaces", "finding_id"},
            label,
        )
        for field in ("owning_producer", "control_key"):
            value = merge.get(field)
            if not isinstance(value, str) or not value.strip():
                raise CreditAnalysisError(f"{label} {field} is invalid")
        merge_key = (merge["owning_producer"], merge["control_key"])
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
        if any(
            review_by_id[review_id]["owning_producer"] != merge["owning_producer"]
            for review_id in eligible_review_ids
        ):
            raise CreditAnalysisError(f"{label} producer ownership is invalid")
        finding_id = merge.get("finding_id")
        if not isinstance(finding_id, str) or finding_id not in finding_by_id or any(
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
    # The review's explicit finding ID is the association. Do not infer a
    # connection from prose similarity, candidate overlap, or call overlap.
    missing_by_finding: dict[str, list[str]] = {}
    missing_review_ids = required_merged - merged_reviews
    for review_id, review in review_by_id.items():
        if review_id in missing_review_ids:
            missing_by_finding.setdefault(review["finding_id"], []).append(review_id)
    for finding_id, missing_ids in missing_by_finding.items():
        owners = {
            review["owning_producer"]
            for review in review_by_id.values()
            if review["finding_id"] == finding_id
        }
        existing = [merge for merge in merges if merge["finding_id"] == finding_id]
        if len(owners) != 1 or len(existing) > 1:
            raise CreditAnalysisError(
                f"temporary-control finding {finding_id} merge ownership is ambiguous"
            )
        owner = next(iter(owners))
        if existing:
            target = existing[0]
        else:
            control = finding_by_id[finding_id]["proposed_durable_control"]
            key = (owner, control)
            if key in merge_keys:
                raise CreditAnalysisError(
                    f"temporary-control finding {finding_id} owner/control is ambiguous"
                )
            merge_keys.add(key)
            target = {
                "control_key": control,
                "owning_producer": owner,
                "review_ids": [],
                "contributing_surfaces": [],
                "finding_id": finding_id,
            }
            merges.append(target)
        target["review_ids"] = [*target["review_ids"], *missing_ids]
        target["contributing_surfaces"] = [
            surface for surface in surface_order
            if any(
                surface in review_by_id[review_id]["contributing_surfaces"]
                for review_id in target["review_ids"]
            )
        ]
        merged_reviews.update(missing_ids)
    if merged_reviews != required_merged:
        raise CreditAnalysisError("temporary-control confirmed findings were not merged once")
    return merges


def _holistic_source_destination(
    prior: Mapping[str, Any],
    outcomes: Mapping[str, Mapping[str, Any]],
    destinations: set[str],
    label: str,
) -> str:
    """Resolve only candidate-linked destinations covering the complete source.

    One candidate can support multiple independent outcomes. An outcome missing
    the source's evidence is not an alternative destination for that source.
    An explicitly retained original ID still has to pass the coverage check.
    """

    def covers(destination: str) -> bool:
        summary = outcomes[destination]
        return (
            prior["workstream"] == summary["workstream"]
            and set(prior["affected_call_ids"]) <= set(summary["affected_call_ids"])
            and set(prior["evidence_refs"]) <= set(summary["evidence_refs"])
        )

    if not destinations:
        raise CreditAnalysisError(f"{label} final ownership is missing")
    if prior["id"] in destinations:
        destination = prior["id"]
    elif len(destinations) == 1:
        destination = next(iter(destinations))
    else:
        covered = [destination for destination in destinations if covers(destination)]
        if not covered:
            raise CreditAnalysisError(f"{label} evidence coverage is incomplete")
        if len(covered) != 1:
            raise CreditAnalysisError(f"{label} final ownership is ambiguous")
        destination = covered[0]
    if not covers(destination):
        raise CreditAnalysisError(f"{label} evidence coverage is incomplete")
    return destination


def _holistic_preserve_finding_sources(
    findings: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    prior_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Retain accepted findings through the final model's candidate links.

    A rewritten summary is not evidence of semantic equivalence. Each original
    finding remains intact in controller-derived ``source_findings`` under one
    destination shared by all of its candidate decisions. The original ID may
    disambiguate destinations, but cannot bypass call or evidence coverage.
    Source records are provenance, not additional findings or savings; final
    judgments and accounting remain with the already validated summary.
    Revalidation compares supplied provenance with the accepted source records.
    """

    finding_by_id = {finding["id"]: finding for finding in findings}
    decision_by_candidate = {
        decision["luna_candidate_id"]: decision for decision in decisions
    }
    prior_by_id: dict[str, Mapping[str, Any]] = {}
    candidates_by_finding: dict[str, set[str]] = {}
    for result in prior_results:
        for finding in result["confirmed_findings"]:
            finding_id = finding["id"]
            if finding_id in prior_by_id and prior_by_id[finding_id] != finding:
                raise CreditAnalysisError(f"prior confirmed finding {finding_id} is conflicting")
            prior_by_id[finding_id] = finding
        for decision in result["candidate_decisions"]:
            for finding_id in decision["finding_ids"]:
                candidates_by_finding.setdefault(finding_id, set()).add(
                    decision["luna_candidate_id"]
                )

    sources: dict[str, list[dict[str, Any]]] = {finding_id: [] for finding_id in finding_by_id}
    for finding_id, prior in prior_by_id.items():
        candidates = candidates_by_finding.get(finding_id, set())
        if not candidates or not candidates <= decision_by_candidate.keys():
            raise CreditAnalysisError(f"prior confirmed finding {finding_id} candidate ownership is missing")
        destinations = set(finding_by_id)
        for candidate_id in candidates:
            destinations.intersection_update(decision_by_candidate[candidate_id]["finding_ids"])
        destination = _holistic_source_destination(
            prior, finding_by_id, destinations, f"prior confirmed finding {finding_id}"
        )
        sources[destination].append(copy.deepcopy(dict(prior)))

    preserved = []
    for finding in findings:
        expected_sources = sources[finding["id"]]
        if "source_findings" in finding and finding["source_findings"] != expected_sources:
            raise CreditAnalysisError(f"confirmed finding {finding['id']} source records changed")
        preserved.append({**finding, "source_findings": expected_sources})
    return preserved


def _holistic_preserve_risk_sources(
    risks: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    prior_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach immutable reviewer risks through already validated candidate links.

    ``source_risks`` is controller-derived provenance, never a model judgment.
    Each source risk must have exactly one destination shared by its candidate
    decisions, with its calls and evidence covered. Retaining its original ID
    disambiguates multiple linked destinations, but never bypasses coverage.
    Source records keep every original uncertainty even when the final model
    rewrites their combined summary. Supplied provenance is checked against
    trusted reviewer records on canonical-result revalidation.
    """

    risk_by_id = {risk["id"]: risk for risk in risks}
    decision_by_candidate = {
        decision["luna_candidate_id"]: decision for decision in decisions
    }
    prior_by_id: dict[str, Mapping[str, Any]] = {}
    candidates_by_risk: dict[str, set[str]] = {}
    for result in prior_results:
        for risk in result["plausible_risks"]:
            risk_id = risk["id"]
            if risk_id in prior_by_id and prior_by_id[risk_id] != risk:
                raise CreditAnalysisError(f"prior plausible risk {risk_id} is conflicting")
            prior_by_id[risk_id] = risk
        for decision in result["candidate_decisions"]:
            for risk_id in decision["risk_ids"]:
                candidates_by_risk.setdefault(risk_id, set()).add(
                    decision["luna_candidate_id"]
                )

    sources: dict[str, list[dict[str, Any]]] = {risk_id: [] for risk_id in risk_by_id}
    for risk_id, prior in prior_by_id.items():
        candidates = candidates_by_risk.get(risk_id, set())
        if not candidates or not candidates <= decision_by_candidate.keys():
            raise CreditAnalysisError(f"prior plausible risk {risk_id} candidate ownership is missing")
        destinations = set(risk_by_id)
        for candidate_id in candidates:
            destinations.intersection_update(decision_by_candidate[candidate_id]["risk_ids"])
        destination = _holistic_source_destination(
            prior, risk_by_id, destinations, f"prior plausible risk {risk_id}"
        )
        sources[destination].append(copy.deepcopy(dict(prior)))

    preserved = []
    for risk in risks:
        expected_sources = sources[risk["id"]]
        if "source_risks" in risk and risk["source_risks"] != expected_sources:
            raise CreditAnalysisError(f"plausible risk {risk['id']} source records changed")
        preserved.append({**risk, "source_risks": expected_sources})
    return preserved


def _holistic_preserve_review_sources(
    reviews: Mapping[str, Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    prior_results: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Keep full reviewer records behind unambiguously consolidated controls.

    Candidate membership identifies possible destinations; an unchanged review
    ID disambiguates multiple controls for the same candidates. Coverage and
    disposition must still agree. A renamed review also needs agreement with
    an already identified owner. A prior finding must remain linked through
    its validated candidate decisions even when the final review dismisses only
    its temporary-control subclaim with an explicit reason.
    ``source_reviews`` preserves the original wording, unknown owners, and ROI
    inputs without replacing the final model's independently validated judgment.
    """

    decision_by_candidate = {
        decision["luna_candidate_id"]: decision for decision in decisions
    }
    resolved_reviews = {
        review_id: copy.deepcopy(dict(review))
        for review_id, review in reviews.items()
    }
    sources: dict[str, list[dict[str, Any]]] = {
        review_id: [] for review_id in resolved_reviews
    }
    prior_by_id: dict[str, Mapping[str, Any]] = {}
    for result in prior_results:
        for prior in result["temporary_control_reviews"]:
            review_id = prior["id"]
            if review_id in prior_by_id:
                if prior_by_id[review_id] != prior:
                    raise CreditAnalysisError(f"prior temporary-control review {review_id} is conflicting")
                continue
            prior_by_id[review_id] = prior
            candidates = set(prior["source_luna_candidate_ids"])
            if review_id in resolved_reviews:
                same_id = resolved_reviews[review_id]
                coverage_fields = (
                    "affected_call_ids",
                    "final_canonical_evidence_refs",
                    "contributing_surfaces",
                )
                same_no_finding = (
                    prior["finding_id"] is None
                    and same_id["finding_id"] is None
                )
                preserves_source = (
                    candidates <= set(same_id["source_luna_candidate_ids"])
                    and (
                        prior["owning_producer"] is None
                        or prior["owning_producer"] == same_id["owning_producer"]
                    )
                    and prior["disposition"] == same_id["disposition"]
                    and all(
                        set(prior[field]) <= set(same_id[field])
                        for field in coverage_fields
                    )
                )
                if same_no_finding and not preserves_source:
                    # A corrected final review may retract a repurposed ID. The
                    # accepted same-ID no-finding source is then authoritative;
                    # copying it preserves evidence without reviving the rejected
                    # final subclaim or changing any independent finding.
                    resolved_reviews[review_id] = copy.deepcopy(dict(prior))
            destinations = [
                review for review in resolved_reviews.values()
                if candidates <= set(review["source_luna_candidate_ids"])
                and (review_id == review["id"] or prior["owning_producer"] is None
                     or prior["owning_producer"] == review["owning_producer"])
            ]
            if review_id in resolved_reviews:
                destination = resolved_reviews[review_id]
            elif len(destinations) == 1:
                destination = destinations[0]
            else:
                raise CreditAnalysisError(
                    f"prior temporary-control review {review_id} final ownership is "
                    + ("missing" if not destinations else "ambiguous")
                )
            if destination not in destinations or any(
                not set(prior[field]) <= set(destination[field])
                for field in ("affected_call_ids", "final_canonical_evidence_refs", "contributing_surfaces")
            ):
                raise CreditAnalysisError(f"prior temporary-control review {review_id} coverage is incomplete")
            if prior["disposition"] != destination["disposition"]:
                raise CreditAnalysisError(f"prior temporary-control review {review_id} disposition changed")
            if prior["finding_id"] is None:
                finding_preserved = destination["finding_id"] is None
            else:
                finding_candidates = {
                    decision["luna_candidate_id"] for decision in result["candidate_decisions"]
                    if prior["finding_id"] in decision["finding_ids"]
                }
                final_destinations: set[str] | None = None
                for candidate in finding_candidates:
                    if candidate not in decision_by_candidate:
                        final_destinations = set()
                        break
                    candidate_destinations = set(
                        decision_by_candidate[candidate]["finding_ids"]
                    )
                    final_destinations = (
                        candidate_destinations
                        if final_destinations is None
                        else final_destinations & candidate_destinations
                    )
                final_destinations = final_destinations or set()
                if destination["finding_id"] is None:
                    finding_preserved = bool(final_destinations) and isinstance(
                        destination.get("no_finding_reason"), str
                    ) and bool(destination["no_finding_reason"].strip())
                else:
                    finding_preserved = destination["finding_id"] in final_destinations
            if not finding_preserved:
                raise CreditAnalysisError(f"prior temporary-control review {review_id} finding ownership changed")
            sources[destination["id"]].append(copy.deepcopy(dict(prior)))

    preserved = {}
    for review_id, review in resolved_reviews.items():
        expected_sources = sources[review_id]
        if "source_reviews" in review and review["source_reviews"] != expected_sources:
            raise CreditAnalysisError(f"temporary-control review {review_id} source records changed")
        preserved[review_id] = {**review, "source_reviews": expected_sources}
    return preserved


def _holistic_category_reviews(
    reviews: Sequence[Mapping[str, Any]],
    categories: Sequence[str],
    prior_results: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Assemble final category summaries from accepted reviewer records.

    The caller validates each record's fields, evidence, boolean, and reason.
    Child reviewers must return one record per category. Final model transport
    contributes no category judgment: an empty current response and a retained
    legacy response without controller provenance both resolve from the accepted
    reviewer records. Applicability across reviewed portions is existential,
    never a vote.

    Controller-generated ``source_reviews`` retains every original assessment
    and its task identity. Canonical revalidation checks supplied provenance and
    the deterministic summary against those accepted records.
    """

    grouped: dict[str, list[Mapping[str, Any]]] = {category: [] for category in categories}
    for review in reviews:
        category = review["category"]
        if not isinstance(category, str) or category not in grouped:
            raise CreditAnalysisError("helper category review references an unknown category")
        grouped[category].append(review)

    def source_records(category: str) -> list[dict[str, Any]]:
        return [
            {"task_id": result["task_id"], "review": copy.deepcopy(dict(review))}
            for result in prior_results or []
            for review in result["helper_category_reviews"]
            if review["category"] == category
        ]

    def inherited_summary(
        category: str, sources: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        applies = any(source["review"]["applies"] for source in sources)
        return {
            "category": category,
            "applies": applies,
            "evidence_refs": list(dict.fromkeys(
                ref for source in sources for ref in source["review"]["evidence_refs"]
            )),
            "reason": (
                "Applicable in at least one reviewed portion; original assessments are retained."
                if applies else
                "No reviewed portion establishes applicability; original assessments are retained."
            ),
        }

    if prior_results is not None and not any(
        "source_reviews" in review for review in reviews
    ):
        assembled = []
        for category in categories:
            sources = source_records(category)
            assembled.append(
                {
                    **inherited_summary(category, sources),
                    "source_reviews": sources,
                }
            )
        return assembled

    missing = [category for category, group in grouped.items() if not group]
    if missing:
        raise CreditAnalysisError("helper category reviews are missing: " + ", ".join(missing))

    normalized = []
    for category, group in grouped.items():
        if prior_results is None:
            if len(group) != 1:
                raise CreditAnalysisError(f"helper category {category} is reviewed more than once")
            normalized.append(dict(group[0]))
            continue
        sources = source_records(category)
        distinct = []
        for review in group:
            if "source_reviews" in review and (
                len(group) != 1 or review["source_reviews"] != sources
            ):
                raise CreditAnalysisError(f"helper category {category} source records changed")
            assessment = {key: value for key, value in review.items() if key != "source_reviews"}
            if assessment not in distinct:
                distinct.append(assessment)
        copied = bool(sources) and all(
            any(review == source["review"] for source in sources)
            for review in distinct
        )
        if len(distinct) > 1 and not copied:
            raise CreditAnalysisError(f"helper category {category} has untraceable repeated assessments")
        prior_applies = any(source["review"]["applies"] for source in sources)
        if copied:
            summary = inherited_summary(category, sources)
        else:
            summary = distinct[0]
            if prior_applies and not summary["applies"]:
                raise CreditAnalysisError(f"helper category {category} dropped supported applicability")
        normalized.append({**summary, "source_reviews": sources})
    return normalized
