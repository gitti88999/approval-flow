# ADR-001 – Microservices Boundaries by Domain Responsibilities

## Status
Accepted

## Context

The system was required to use a microservices architecture, but the assignment did not define how the services should be divided.

The main architectural challenge was defining service boundaries that would maintain clear ownership and reduce coupling.

The system contains several distinct business responsibilities:

- Invoice ingestion and validation.
- Approval decision processing.
- Payment processing.
- Gateway and resilience concerns.

## Decision

Service boundaries were defined according to domain responsibilities rather than technical layers.

The system was divided into the following services:

### Ingestion Service
Responsible for:
- Receiving invoice submissions.
- Initial validation.
- Idempotency checks.
- Publishing invoice events.

### Approval Agent Service
Responsible for:
- Loading business policy.
- Evaluating approval decisions.
- Managing approval workflow state.

### Payment Service
Responsible for:
- Payment execution workflow.
- Payment state management.
- Handling payment success and failure states.

### Gateway Service
Responsible for:
- Authentication.
- Routing.
- Resilience mechanisms.

## Alternatives Considered

### Single Backend Application

Rejected because it would combine multiple business domains into one deployable component.

This would increase coupling and make independent scaling and testing harder.

### Splitting Services by Technical Layers

Rejected because technical separation does not represent business ownership.

Services should represent business capabilities rather than controllers, databases, or infrastructure layers.

## Consequences

### Positive

- Clear ownership of responsibilities.
- Independent testing of business domains.
- Ability to evolve services independently.

### Negative

- More operational components.
- Additional communication complexity.
- Distributed debugging becomes more challenging.