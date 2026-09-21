# Phase 7 independent review record

Copy this file for the completed review. Do not edit the template in place.
The reviewer must not have implemented any commit in the reviewed range.

## Candidate identity

- Baseline commit: `4838e51`
- Candidate commit: `4a73017f90bd11813570ffda6b8c465851697f89`
- Reviewer:
- Reviewer independence statement:
- Review start and completion dates:
- Host and Python/Home Assistant test environment:

The review is invalid if the candidate hash differs or the checkout contains
uncommitted files.

## Mechanical verification

Record the exit code and concise result for every command in the
[review packet](phase-7-independent-review-packet.md). Do not replace the full
suite with a focused subset.

| Gate | Result | Evidence or output reference |
| --- | --- | --- |
| Candidate hash and clean checkout | Pending | |
| Full repository suite (expected 956) | Pending | |
| Frozen compatibility contracts (expected 24) | Pending | |
| Current → `v0.12.26` → current round trip | Pending | |
| Controller boundary contract | Pending | |
| Persistence boundary contract | Pending | |
| Ruff | Pending | |
| Range diff check | Pending | |

## Manual invariant review

For each item record **Pass**, **Fail**, or **Not reviewed** plus the exact
files, transitions and tests inspected. A test name alone is not sufficient.

| Invariant | Result | Evidence and reasoning |
| --- | --- | --- |
| Safety Lock causes no hardware call or retry consumption | Not reviewed | |
| Ownership and sign gates fail closed | Not reviewed | |
| Stale, missing, contradictory and malformed evidence fail safely | Not reviewed | |
| Charge, export, manual-test and EV obligations survive reload | Not reviewed | |
| External forced modes are never silently adopted | Not reviewed | |
| EV priorities, boundaries, feedback and battery floor are preserved | Not reviewed | |
| Service payload, order, delay and retry behaviour are preserved | Not reviewed | |
| Store keys, versions, privacy and payloads are unchanged | Not reviewed | |
| Entity, attribute, config and Fleet contracts are unchanged | Not reviewed | |
| Only adapters can issue hardware service calls | Not reviewed | |
| No Phase 8 scheduling or cadence change entered the candidate | Not reviewed | |

## Findings

Use one row per finding. Severity is **P0** (unsafe command/data loss), **P1**
(contract or restoration failure), **P2** (maintainability defect with bounded
runtime risk), or **P3** (documentation/clarity). Every P0/P1 requires a
deterministic regression, correction and reviewer re-check before acceptance.

| ID | Severity | File/line | Violated invariant | Reproduction or evidence | Resolution commit | Re-review result |
| --- | --- | --- | --- | --- | --- | --- |
| None recorded | — | — | — | — | — | — |

## Residual risks

List unresolved P2/P3 findings, assumptions, untested environments and any
reason the deterministic evidence may not represent an operational site.

## Decision

Select exactly one:

- [ ] **Accepted** — all checklist items pass, no P0/P1 remains, and residual
  risks are explicitly recorded.
- [ ] **Rejected** — one or more invariant, evidence or independence gate
  failed.
- [ ] **Incomplete** — review stopped before a valid decision.

Decision rationale:

Reviewer name and date:

Project-owner acknowledgement and date:

Acceptance authorizes only the next programme gate. It does not authorize a
push, release, deployment or live-site command.
