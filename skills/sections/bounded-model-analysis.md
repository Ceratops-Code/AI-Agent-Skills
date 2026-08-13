<!-- INTERNAL: include in skills that invoke bounded analysis-only child
models -->

## Bounded Model Analysis Contract

- Invoke only the model, reasoning effort, call count, and eligibility condition
  named by the owning skill; do not substitute another model, effort, or extra
  call.
- Give each child only the controller- or helper-retained evidence selected for
  that analysis. Give it no tools or mutation authority.
- Use child models only for semantic judgment. Keep retrieval, selection,
  ordering, validation, arithmetic, persistence, and cleanup in deterministic
  code when the owning workflow provides it.
- If the required child configuration is unavailable, preserve the deterministic
  evidence and report the exact blocker; do not bypass the boundary or make a
  fallback model call.
