# Architecture at a glance

```mermaid
flowchart LR
  A[Topic selection] --> B[Human-approved queue]
  A -. optional, budget-bounded .-> D[DataForSEO]
  B --> C[Research]
  C --> E[Brief]
  E --> F[Assets]
  F --> G[Writer]
  G --> H[QA evaluation]
  H --> I[Human publication review]
  I --> J[Website export + tests]
  J --> K[GitHub + Cloudflare Pages]
  C -. claims + sources .-> L[Traceability]
  H -. handoff receipts + hashes .-> L
  A -. budget / scope stops .-> M[Control gates]
  H -. quality stops .-> M
```

The design separates editorial work from control logic. The seven skills define their responsibilities and output expectations. The lightweight orchestrator persists state, validates handoffs and enforces approvals; it does not make editorial decisions or run unattended.

The optional DataForSEO boundary is deliberately narrow: request plans are checked against scope and budget before a live request, responses are retained for traceability, and collection stops if billing is unresolved.
