---
name: openai-docs-managed
description: Retrieve and answer current official OpenAI product, API, model, ChatGPT, and Codex documentation through a deterministic allowlisted helper. Use for OpenAI documentation questions, Codex setup or troubleshooting, model selection or migration, and explicit independent synthesis from retrieved official evidence.
---

# Managed OpenAI Docs

## Goal

Answer current OpenAI documentation questions from opened official source pages
while keeping routine retrieval deterministic and model-free.

## Context

### Inputs To Capture

- The user's documentation question.
- The exact requested product and model names, when present.
- One optional primary route: `api`, `codex`, `chatgpt`,
  `model-selection`, `model-migration`, or `troubleshooting`.
- Whether the caller explicitly requests independent synthesis.

Infer only the route when it is omitted. Preserve every explicit product or
model name exactly as supplied.

## Constraints

### Semantic Policy

- Interpret the request, select at most one primary route, and pass factual
  retrieval to the bundled helper.
- From this installed skill directory, create the helper's closed JSON request
  and run `python scripts/openai_docs_retrieval.py --request <request.json>`.
- The request contains exactly `schema`, `query`, `requested_product`,
  `requested_model`, `route`, and `independent_synthesis`; use `null` for an
  omitted product, model, or route.
- Treat an explicit model name as opaque text. Never normalize, upgrade,
  alias, or substitute it.
- Consume the returned record as the factual source of truth. Do not search,
  open, or fetch documentation again for facts already established or rejected
  by the helper.
- Answer only from the record's opened-page claim evidence and cite its source
  URLs. Preserve unresolved ambiguity and exact blockers instead of completing
  an unsupported answer from memory.
- Routine retrieval uses no child model. A child is eligible only when the
  caller explicitly requested independent synthesis or the record reports
  `semantic_reconciliation_required`.
- When eligible and supported by the runtime, invoke exactly one analysis-only
  `gpt-5.6-luna` child at low reasoning effort. Give it only the retained JSON
  record, no tools, and no file-mutation authority. It may summarize or
  reconcile that record only; never substitute another model or effort.
- If the required child configuration is unavailable, retain the deterministic
  record, report the escalation blocker, and do not make another model call.

### Boundaries

- Use this skill for current official OpenAI product, API, model, ChatGPT, and
  Codex documentation, including setup, architecture, model selection,
  migration, and troubleshooting questions.
- Do not use it for generic software questions that merely mention an OpenAI
  product without needing OpenAI documentation.
- Read-only documentation retrieval requires no API key.
- The helper is the sole retrieval boundary and allows only
  `developers.openai.com`, `platform.openai.com`, and `learn.chatgpt.com`.
- Search indexes and snippets are routing evidence only. A claim is usable only
  after the helper opens its actual source page.
- Rank and validate required concepts through code-owned named-surface and
  semantic-alias sets. On one opened page, require the named surface plus a
  payload concept; treat unregistered phrases compositionally.
- For unspecified current-model migration, exclude older version guides from
  filler slots. Compare support polarity only within anchor-bearing sentences
  or rows.
- Within the selected route, continue past non-policy page-open failures within
  the coded fetch-attempt bound until the opened-page limit is reached; never
  select another route.
- Unavailable, disallowed-redirect, conflicting, and insufficient documentation
  states are blockers or ambiguity, not permission to invent an answer.

## Workflow

1. Capture the exact question, product, model, optional route, and independent
   synthesis request.
2. Run the bundled helper once and parse its single bounded JSON record.
3. Stop factual retrieval. Use only opened-page claim evidence from the record.
4. If the record permits escalation, use at most one Luna-low analysis child
   under the stated no-tool, no-mutation boundary.
5. Answer concisely with source links and disclose unresolved ambiguity or the
   exact blocker.

## Done When

### Completion Gate

- One valid helper record was consumed.
- Every factual claim in the answer maps to opened-page evidence in that record.
- Any child call satisfied the record's eligibility, model, effort, call-count,
  tool, and mutation constraints.
- Ambiguity and blockers remain visible without unsupported completion.

### Output Contract

Return only:

- the supported answer with direct official source links
- unresolved ambiguity that affects the answer
- the exact blocker when the documentation record is not answerable
- whether an eligible independent synthesis was unavailable
