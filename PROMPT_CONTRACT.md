# Prompt Contract

This project does not treat prompts as free-form writing requests.
Every agent prompt must obey a contract.

## Core Rule

No agent may output a factual claim unless the claim is backed by approved evidence.

## Required Sections

Every production prompt should explicitly define:

- `task`
- `source_scope`
- `evidence_requirements`
- `forbidden_behaviors`
- `output_contract`
- `review_gate`

## Non-Negotiable Constraints

- Do not invent scores, records, injuries, quotes, or trends.
- Do not turn an observation into a fact statement without evidence.
- Do not omit the time window of the data.
- Do not mix platform voice across Hupu and Douyin.
- Do not use unsupported absolute language.

## Claim Rules

- Primary claims need at least 2 evidence points.
- Primary claims should meet confidence `>= 0.80`.
- If confidence is lower, downgrade the statement to an observation.
- If evidence is missing, do not generate the claim.

## Output Rules

- Selector outputs ranked matches and a recommended angle.
- Fact researcher outputs evidence packets, not conclusions.
- Writer outputs platform packages using only approved evidence.
- Fact checker audits evidence count and confidence.
- Risk guard audits wording, staleness, and unsafe exaggeration.
- Publisher only prepares release actions after the two review roles pass.
