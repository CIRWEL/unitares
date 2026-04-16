# Contract Drift Playbook

Status: specialized engineering playbook. Use for tool-contract changes and drift prevention, not as a user/operator guide.

**Created:** March 14, 2026  
**Last Updated:** March 14, 2026  
**Doc State:** Active

---

## Purpose

Keep tool contracts aligned across:
- handler behavior
- Pydantic/tool schemas
- introspection/listing examples
- migration notes and user-facing hints

Contract drift is any mismatch between those surfaces.

## Sources of Truth

- **Behavior truth:** handler implementation in `src/mcp_handlers/`
- **Schema truth:** Pydantic schemas in `src/mcp_handlers/schemas/`
- **Discovery truth:** introspection text in `src/mcp_handlers/introspection/tool_introspection.py`
- **Migration truth:** `src/mcp_handlers/tool_stability.py`

When changing one, check all four.

## Rules

- Use one canonical user-facing path per workflow (for example, `knowledge(action='search')`).
- Centralize reusable hint strings in shared constants (for example, `src/mcp_handlers/support/tool_hints.py`).
- Avoid copying guidance text directly into multiple handlers.
- Add compatibility aliases in handlers for old values when practical (for example, `status='active'` -> `open`).
- If aliases are added, document them in schema descriptions and examples.

## Change Checklist (Required)

- Update handler behavior.
- Update schema field descriptions and coercion logic if needed.
- Update introspection/list tool examples.
- Update migration notes/deprecation text.
- Add or update tests for:
  - behavior
  - schema contract
  - guidance consistency (string drift guard where applicable)

## Test Strategy

- For focused iteration, run targeted tests with `--no-cov` to avoid coverage gate noise.
- Before push, run/allow the full repository suite and hooks.
- Prefer small, focused commits to isolate contract-level changes from unrelated refactors.

## Multi-Agent Worktree Guidance

- Stage only files owned by the current task.
- Do not revert unrelated files changed by other agents.
- If overlapping edits appear in the same file, pause and coordinate before force-resolving.

## Common Drift Patterns to Watch

- schema enum differs from accepted runtime value
- examples still point to deprecated tool
- recovery hints reference old tool names
- introspection signatures omit supported parameters

## Escalation Rule

If a contract decision impacts security or authorization semantics (for example, `agent_id` override behavior), require explicit policy sign-off before broad rollout.

## Practical Workflow

Use this sequence for any tool-surface change:

1. Identify the user-visible contract you are changing. Write it in one sentence first.
2. Implement the behavior change in the handler.
3. Update schema and coercion rules so validation matches runtime behavior.
4. Update introspection and migration strings so agents see the same guidance.
5. Add tests that fail if old behavior or legacy wording returns.
6. Run targeted tests for fast iteration.
7. Run full tests (or rely on pre-push hook) before pushing.

The key idea: behavior-only changes are incomplete. A contract is not just code execution; it is the combined promise represented by runtime behavior, schema affordances, examples, and recovery hints.

## Example Drift Case: Search API Naming

A common drift pattern in this codebase is tool naming transitions. The runtime may support both legacy and consolidated flows during migration windows. If guidance strings are not updated together, agents will continue to call old APIs even when new APIs are preferred.

Example:
- Runtime supports `knowledge(action='search', ...)`
- A schema still describes legacy `search_knowledge_graph` filters
- An onboarding hint says "Use search_knowledge_graph..."
- A migration note points somewhere else

Result:
- agents receive inconsistent instructions
- support burden increases
- debugging appears like functional breakage even when behavior is technically correct

Mitigation:
- centralize canonical hint strings in one file
- consume those constants in all user-facing contexts
- add drift tests that scan key files for forbidden legacy guidance fragments

## Definition of Done for Contract Changes

A contract-affecting PR is only done when all conditions below are true:

- The handler accepts and returns the intended values.
- Schema descriptions match what runtime actually accepts.
- User-facing guidance strings reference canonical tool paths.
- Introspection signatures and examples are accurate.
- Migration notes are updated when deprecations are involved.
- Compatibility aliases are explicitly documented (if retained).
- Tests cover both happy path and drift prevention checks.

If any one of these is missing, treat the change as partial.

## Ownership and Review Notes

For multi-agent development, assign explicit ownership by surface:
- one owner for runtime logic
- one owner for schema/introspection wording
- one owner for migration and alias compatibility

In small changes, one person can own all three, but reviewers should still use this playbook as a checklist. Avoid "looks good" reviews that only inspect handler diffs.

## Anti-Patterns

- Updating examples without updating runtime behavior.
- Updating runtime behavior without schema description changes.
- Adding alias compatibility without documenting migration intent.
- Leaving old hint text "temporarily" and expecting later cleanup.
- Shipping broad wording edits without tests that enforce the new canonical phrasing.

## Suggested PR Template Snippet

Include this in PR descriptions for tool-contract changes:

- **Contract changed:** `<one sentence>`
- **Behavior updated in:** `<files>`
- **Schema updated in:** `<files>`
- **Introspection/migration updated in:** `<files>`
- **Compatibility aliases:** `<none | list>`
- **Drift guard tests added/updated:** `<files>`

Using a standard snippet makes drift visible during review and prevents accidental omission of one surface.
