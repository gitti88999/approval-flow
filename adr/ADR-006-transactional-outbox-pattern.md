# ADR-006 – Transactional Outbox for Reliable Event Publishing

## Status
Accepted

## Context

The system relies on asynchronous communication through events.

Publishing an event directly after updating business state creates a risk:
- The business state may be committed.
- The event publication may fail.
- Other services may never receive the required event.

This can leave the workflow in an inconsistent state.

## Decision

The system uses a Transactional Outbox pattern for reliable event publishing.

Events are persisted before being published externally.

A background dispatcher retries failed publications until successful delivery.

## Alternatives Considered

### Direct Event Publishing

Rejected because a temporary infrastructure failure could permanently lose events.

### Distributed Transaction Between State Update and Event Publishing

Rejected because it introduces strong coupling between services.

## Consequences

### Positive

- Reduced risk of event loss.
- Retry capability after temporary failures.
- Better reliability in asynchronous workflows.

### Negative

- Additional persistence logic.
- Event delivery becomes eventually consistent.
- Requires monitoring of pending events.