# Software Design

Replace the empty declarations with evidence; this seed is not a completed
design. Keep the declared source hierarchy in precedence order and distinguish
current implementation from approved intent in each relevant section.

```design-document
{
  "contract_version": 1,
  "document": "docs/design.md",
  "owners": [],
  "source_of_truth": [],
  "update_triggers": [],
  "coverage": {
    "purpose": {"heading": "1 Purpose and goals", "status": "unverified", "reason": "Awaiting repository evidence"},
    "constraints": {"heading": "2 Constraints and assumptions", "status": "unverified", "reason": "Awaiting repository evidence"},
    "context": {"heading": "3 System context", "status": "unverified", "reason": "Awaiting repository evidence"},
    "strategy": {"heading": "4 Solution strategy", "status": "unverified", "reason": "Awaiting repository evidence"},
    "building_blocks": {"heading": "5 Building blocks", "status": "unverified", "reason": "Awaiting repository evidence"},
    "runtime": {"heading": "6 Runtime behavior", "status": "unverified", "reason": "Awaiting repository evidence"},
    "deployment": {"heading": "7 Deployment and operations", "status": "unverified", "reason": "Awaiting repository evidence"},
    "data": {"heading": "8.1 Data and persistence", "status": "unverified", "reason": "Awaiting repository evidence"},
    "interfaces": {"heading": "8.2 APIs and integrations", "status": "unverified", "reason": "Awaiting repository evidence"},
    "protection": {"heading": "8.3 Security and resilience", "status": "unverified", "reason": "Awaiting repository evidence"},
    "decisions": {"heading": "9 Decisions and alternatives", "status": "unverified", "reason": "Awaiting repository evidence"},
    "quality": {"heading": "10 Quality scenarios", "status": "unverified", "reason": "Awaiting repository evidence"},
    "risks": {"heading": "11 Risks and limitations", "status": "unverified", "reason": "Awaiting repository evidence"},
    "glossary": {"heading": "12 Glossary and references", "status": "unverified", "reason": "Awaiting repository evidence"},
    "verification": {"heading": "13 Testing and verification", "status": "unverified", "reason": "Awaiting repository evidence"},
    "governance": {"heading": "14 Ownership and maintenance", "status": "unverified", "reason": "Awaiting repository evidence"}
  }
}
```

## 1 Purpose and goals

State purpose, scope, stakeholders, intended readers, prerequisite knowledge,
goals, and non-goals; identify the design questions readers must decide and
prioritize the architectural quality goals that drive them.

## 2 Constraints and assumptions

Separate imposed constraints from assumptions; give assumptions an owner or a
way to verify them.

## 3 System context

Describe the system boundary, users, external dependencies, trust boundaries,
and the responsibilities on each side.

## 4 Solution strategy

Explain the approach, its important tradeoffs, and how it supports goals under
the constraints.

## 5 Building blocks

Identify major applications, stores, modules, responsibilities, interfaces,
and implementation locations at useful levels of detail.

## 6 Runtime behavior

Explain important successful and failing sequences, state changes,
concurrency, retry or idempotency behavior, and recovery when relevant.

## 7 Deployment and operations

Map executable units to environments and infrastructure; cover configuration,
rollout, observability, and operational ownership. For a library or local
tool, state its host/runtime expectations.

## 8 Cross-cutting design

### 8.1 Data and persistence

When state is managed, explain the data model, persistence, schema authority,
lifecycle, migration, compatibility, and rollback or irreversible transitions.

### 8.2 APIs and integrations

When interfaces exist, link their authoritative contracts and describe
authentication, payloads, errors, versioning, timeouts, and compatibility
obligations.

### 8.3 Security and resilience

Assess security, privacy, reliability, backup, and recovery applicability
individually; describe relevant trust and access controls, sensitive data
handling, failure containment, retention, restore objectives, and evidence. Do
not waive this whole topic merely because one part is inapplicable.

## 9 Decisions and alternatives

Record consequential architectural decisions, status, reasoning, and rejected
alternatives; link accepted ADRs without duplicating their authority.

## 10 Quality scenarios

Define measurable scenarios with stimulus, operating conditions, affected
element, expected response, threshold, and verification method; distinguish
desired targets from measured results.

## 11 Risks and limitations

Record concrete risks, technical debt, known limitations, consequence,
mitigation or acceptance, and ownership; do not silently treat unknown
behavior as supported.

## 12 Glossary and references

Define domain terms and link authoritative references. Use one identity for
each architectural element across prose, diagrams, and implementation.

## 13 Testing and verification

Map material design claims and quality scenarios to behavior tests,
integration or migration checks, operational evidence, and remaining
verification gaps.

## 14 Ownership and maintenance

Name the document owner, authoritative path, source-of-truth hierarchy, and
update triggers. Explain how code, APIs, data, deployment, decisions, and
quality changes trigger a design review.
