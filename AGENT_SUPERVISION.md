# Agent Supervision

The system is designed around bounded roles, not one unbounded agent.

## Roles

### Selector

- decides which matches deserve to enter the topic pool
- may read topic scores and fact summaries
- may not write final platform content

### Fact Researcher

- retrieves structured facts and text evidence
- may output research packets only
- may not publish conclusions as final copy

### Writer

- converts approved evidence into platform packages
- may not invent data or override evidence gating

### Fact Checker

- verifies evidence count and confidence thresholds
- may block unsupported claims

### Risk Guard

- checks exaggeration, stale sourcing, and unsafe wording
- may block packages even if the facts are technically correct

### Publisher

- prepares or executes publishing only after review passes

## Supervision Chain

- `selector` -> reviewed by `fact_checker`
- `fact_researcher` -> reviewed by `fact_checker`
- `writer` -> reviewed by `risk_guard`
- `fact_checker` and `risk_guard` -> gate `publisher`

## Blocking Rules

- Any failed fact check blocks publish.
- Any failed risk review blocks publish.
- Warning-level review requires manual confirmation.

## Product Goal

The project should behave like an auditable editorial system:

- clear ownership
- clear evidence boundaries
- clear review gates
- visible reasons for every important decision
