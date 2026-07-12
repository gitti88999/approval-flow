# ADR-002 – Using Dapr as an Infrastructure Abstraction Layer

## Status
Accepted

## Context

The system required the use of Dapr for distributed application capabilities.

A decision was required whether services should directly access infrastructure components or communicate through Dapr abstractions.

## Decision

Dapr is used as the infrastructure abstraction layer.

The application uses Dapr for:

- Pub/Sub messaging.
- State management.
- Configuration access.
- Infrastructure communication.

Application services communicate with Dapr APIs instead of directly accessing Redis or other infrastructure implementations.

## Alternatives Considered

### Direct Redis Client Usage

Rejected because it would couple business services to a specific storage implementation.

### Direct Message Broker SDK

Rejected because every service would contain infrastructure-specific communication code.

### Direct Infrastructure Access

Rejected because infrastructure concerns should remain outside business logic.

## Consequences

### Positive

- Cleaner business services.
- Reduced infrastructure coupling.
- Consistent communication pattern.

### Negative

- Additional dependency on Dapr runtime.
- Additional operational component.