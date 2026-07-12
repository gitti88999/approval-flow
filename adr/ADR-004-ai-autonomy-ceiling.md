# ADR-004 – AI Autonomy Ceiling

## Status
Accepted

## Context

The system uses an LLM to assist with invoice approval decisions.

A language model is probabilistic and cannot be considered the source of truth for mandatory business rules.

Potential risks:

- Incorrect approval decisions.
- Ignoring hard business constraints.
- Prompt injection influence.

## Decision

The LLM is used as a decision assistant, not as the final authority.

Every AI decision is controlled by deterministic validation.

The system enforces:

- Hard stops before LLM invocation.
- Policy constraints outside the model.
- Validation of model output before acceptance.

## Alternatives Considered

### Full Trust in LLM Decisions

Rejected because model behavior cannot be guaranteed to always follow business policy.

## Consequences

### Positive

- AI capability with controlled risk.
- Deterministic enforcement of critical rules.
- Better auditability.

### Negative

- Reduced model autonomy.
- Additional validation logic.

The system intentionally sacrifices some AI autonomy in favor of deterministic compliance and auditability.