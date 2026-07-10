# ADR-003 – Event-Driven Choreography with Local Payment Saga

## Status
Accepted

## Context

The invoice processing workflow spans multiple distributed services:

- Ingestion Service.
- Approval Agent Service.
- Payment Service.

Since each service owns its own data and transactions, there is no single ACID transaction that can cover the complete workflow.

The system requires a mechanism that allows services to remain independent while maintaining consistency during failures.

## Decision

The system uses an event-driven choreography approach between services.

Each service:

- Reacts to relevant domain events.
- Performs its own local transaction.
- Publishes events to continue the workflow.

For the payment process specifically, a local Saga pattern is implemented inside Payment Service.

The payment workflow consists of:

1. Reserve payment state.
2. Execute payment operation.
3. Commit successful payment.
4. Compensate the local reservation state when payment execution fails.

The compensation action is limited to Payment Service state management. It does not perform rollback actions in other services.

## Alternatives Considered

### Distributed Transaction

Rejected because:

- It would create strong coupling between services.
- It is difficult to maintain in a microservices environment.
- It reduces service independence.

### Central Saga Orchestrator

Rejected because the current workflow naturally follows event-driven choreography.

A central coordinator would introduce additional complexity without a current business requirement.

## Consequences

### Positive

- Services remain independent.
- No distributed transaction manager is required.
- Payment consistency is maintained within its own service boundary.
- New event consumers can be added without changing existing services.

### Negative

- There is no global rollback across all services.
- Debugging requires tracing events across components.
- Consistency is achieved through workflow design rather than ACID transactions.