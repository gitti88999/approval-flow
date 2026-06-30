# Project Architecture Documentation

This document describes the high-level system architecture and component design for the Automated Invoice Approval Workflow system powered by **FastAPI** and **Dapr**.

## System Components Overview

The system architecture relies on decoupled microservices that communicate asynchronously using Dapr building blocks (State Management and Publish/Subscribe).

1. **Ingestion Service**: Entry point for all incoming invoices. Validates payload schemas and registers structural idempotency fingerprints.
2. **Dapr Sidecars**: Offloads distributed state holding and pub/sub message brokering topology from application logic.
3. **Redis Store**: Shared backing component serving simultaneously as the transaction persistence layer and communication backbone message broker.

---

## Architecture Component Diagram

Below is the structured topology mapping the runtime flow of an invoice transaction through the platform.

```mermaid
graph TD
    Client[Client / Swagger UI] -->|1. POST /submit| Ingestion[Ingestion Service FastAPI]
    
    subgraph Dapr Sidecar Architecture
        Ingestion -->|2. Get/Set Fingerprint| DaprState[Dapr State Store Block]
        Ingestion -->|4. Publish Event| DaprPubSub[Dapr Pub/Sub Block]
    end

    subgraph Infrastructure Layer
        DaprState -->|3. Read/Write Key| Redis[(Redis DB - M4/M5)]
        DaprPubSub -->|5. Broker Message| Redis
    end

    style Ingestion fill:#f9f,stroke:#333,stroke-width:2px
    style Redis fill:#bbf,stroke:#333,stroke-width:2px
```

---

## Transaction Lifecycles & Rules

### Phase 1: Structural Validation
* Payload parameters are statically type-checked utilizing strict Pydantic parsing filters inside the schemas compilation layer.
* Invoices containing empty parameters, malformed structural bounds, or zero/negative monetary counters are dropped before ingestion processing.

### Phase 2: Idempotency Verification (```GLOBAL-DUP```)
* Unique transaction fingerprint signatures are evaluated against the centralized cache. 
* Duplicated identifiers matching identical criteria instantly prompt a ```409 Conflict``` resolution response.