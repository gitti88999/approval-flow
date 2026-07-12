# ADR-005 – External Policy Management

## Status
Accepted

## Context

Approval rules represent business policy and may change independently from application code.

Keeping policy values inside source code would require code changes and redeployment for every business rule update.

## Decision

Business policy is stored externally and loaded at runtime.

The application is responsible for enforcing the policy rules, while policy values remain outside the application code.

The loaded policy structure is checked before being used by the approval flow.

## Alternatives Considered

### Hardcoded Policy Rules

Rejected because every policy change would require:

- Source code modification.
- Testing.
- New deployment.

## Consequences

### Positive

- Business rules can change without modifying application logic.
- Clear separation between business policy and implementation.
- Easier maintenance and configuration management.

### Negative

- External configuration must be managed correctly.
- Policy structure requires checking before use.
- Runtime dependency on the configuration source.