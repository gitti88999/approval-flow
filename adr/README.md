# Architecture Decision Records

This directory contains the major architectural decisions made during the design and implementation of the Approval Flow system.

Each ADR documents:

- The context that led to the decision.
- The chosen solution.
- Alternatives considered.
- Trade-offs and consequences.

The goal is to preserve architectural reasoning, not only describe implementation details.

---

## Known Architectural Trade-offs

The system intentionally keeps some architectural boundaries simple due to project scope.

The following trade-offs are documented and considered acceptable for the current scale:

- Payment idempotency can be strengthened around in-progress states to provide stronger protection against concurrent duplicate processing.

- Outbox reliability is currently implemented where required by the workflow. A future improvement would extract this capability into a shared infrastructure component for consistent usage across services.

- Event contracts are currently internal between services. As the number of consumers grows, explicit event schemas and versioning may be introduced.