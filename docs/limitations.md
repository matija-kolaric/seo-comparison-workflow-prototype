# Prototype limitations and production considerations

## Current prototype boundaries

- Research quality depends on the supplied sources and human review of their interpretation.
- Pricing, availability and plan limits are time-sensitive and need a fresh official-source check before release.
- The workflow does not perform hands-on product benchmarks or claim representative customer sentiment without appropriate evidence.
- The static website is a preview and deliberately remains `noindex`.
- The tool-fit selector is transparent browser-side scoring among the researched tools. It is not a universal recommendation engine, and it stores no visitor data.

## What production would add

- Managed secrets, role-based access and production audit logs
- A durable job runner, operational monitoring and retry policy
- Formal source-refresh and legal/asset-review processes
- Broader evaluation suites, regression fixtures and editorial review workflows
- A publishing workflow with production metadata, ownership and compliance requirements
- A versioned product-facts layer before expanding the selector beyond the reviewed tools
