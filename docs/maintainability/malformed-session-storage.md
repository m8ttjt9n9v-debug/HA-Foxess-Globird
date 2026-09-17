# Malformed session storage safety decision

The project owner approved the conservative fail-closed behaviour on
2026-09-17: when the inverter is forced and retained ownership evidence is
missing or unreadable, HEO reports `ownership_unknown` and issues no hardware
command until Self Use or a verified external owner establishes a safe mode.
This applies to the charge, export and manual-diagnostic restoration
obligations persisted by HEO.

## Implemented safety slice

- Each legacy version-1 loader now classifies its evidence as valid, missing or
  malformed without changing the existing key or payload format.
- A forced mode with degraded evidence is read-only and surfaces
  `ownership_unknown` through Orchestrator Status and Fleet Summary.
- Malformed payloads are retained unchanged while the inverter remains forced.
- Observed Self Use establishes a safe boundary, checkpoints idle legacy
  payloads, and permits normal evaluation from that verified baseline.
- A forced mode with complete valid idle evidence is treated as externally
  owned and is not adopted or altered.
- A valid unfinished obligation remains authoritative when its matching mode,
  or Self Use during restoration, is observed; unrelated missing stores do not
  erase that obligation.

System lifecycle fixtures cover missing evidence, semantic corruption in all
three stores, safe-mode recovery, external forced mode, and retained active
obligations. The versioned previous-snapshot envelope below remains a separate
persistence-hardening proposal rather than part of this compatibility slice.

## Concrete problem and evidence

HEO currently stores each active session in a private Home Assistant `Store`
using a stable version-1 key. The charge and export loaders validate semantic
fields, then replace malformed payloads with an in-memory idle state. Home
Assistant itself handles invalid JSON by preserving the corrupt file under a
new name, raising a repair issue and returning no payload.

An idle fallback is safe from unauthorized writes, but it cannot prove whether
an observed Force Charge or Force Discharge mode was previously owned by HEO.
Two required safety properties then conflict:

1. HEO must not adopt or modify a forced mode that belongs to an installer,
   inverter schedule or another controller.
2. HEO must not erase its own unfinished restoration obligation because a
   retained payload is missing or malformed.

Actuator feedback alone cannot distinguish those histories. A correct fix must
retain stronger ownership evidence; guessing from the current mode is unsafe.

## Current observable contract

- Storage keys, version and privacy are frozen by
  `persistence-contract-v0.12.26.json`.
- Valid active, starting, stopping and recovering payloads survive setup and
  reload and retain bounded command obligations.
- Unavailable actuator feedback converts an owned active session to recovering
  without issuing a command.
- A completed charge latch does not adopt an unrelated forced mode.
- Invalid semantic payloads fall back to idle in memory.
- Invalid JSON is handled by Home Assistant's storage layer and is not exposed
  to the integration as recoverable data.

## Invariants

- Never infer HEO ownership solely from Force Charge or Force Discharge
  feedback.
- Never issue a hardware command when ownership is unknown.
- Never overwrite malformed evidence before diagnostics and recovery have had
  an opportunity to inspect it.
- Preserve existing storage keys and accept every valid version-1 payload.
- A valid stopping/recovering obligation must survive restart, reload and
  reconfiguration.
- Recovery retries remain bounded and Safety Lock remains absolute.

## Non-goals

- Recovering arbitrary physical disk corruption without a Home Assistant
  backup.
- Taking control from FoxCloud, an inverter-local schedule or another owner.
- Combining independent state families into one persistence payload.
- Changing charge, export or manual-test policy.

## Remaining candidate design

Implement this only in the versioned-persistence phase:

1. Enable atomic writes for safety-critical session stores to reduce partial
   writes during an unclean shutdown.
2. Wrap each state family in its own typed repository while retaining its
   existing key and accepting the legacy version-1 payload.
3. Persist a validated current snapshot plus the immediately previous valid
   snapshot and a monotonic sequence in the same family payload.
4. On a semantically malformed current snapshot, restore the previous valid
   snapshot, expose a repair/diagnostic condition and retain the malformed
   evidence until a successful checkpoint.
5. The approved fail-closed gate remains authoritative if neither snapshot is
   trustworthy; do not infer ownership from actuator mode.
6. Demonstrate upgrade and one-version rollback using valid legacy, malformed
   current, valid previous, missing and future-version fixtures.

Atomic writes and a previous snapshot materially reduce preventable loss. They
cannot make an already missing or wholly unreadable file prove ownership; that
last case requires an explicit product/safety decision rather than an implicit
command.

## Compatibility and rollback

- Existing key names remain unchanged.
- A new envelope requires an explicit store schema version and a reader that
  accepts legacy version 1.
- The previous release must either understand the written payload or the
  rollout must retain a rollback-compatible representation until the rollback
  window closes.
- No implementation may ship until old → new → old restoration is exercised
  with fixture-backed storage files.

## Required tests

- valid legacy payload for every session phase;
- malformed current plus valid previous snapshot;
- missing, invalid JSON, wrong types, negative values and unknown phase;
- unavailable feedback during recovery;
- Safety Lock and non-Modbus ownership throughout recovery;
- exact boundary while ownership evidence is degraded;
- bounded retries and persistent repair status; and
- upgrade, reload, restart and one-version rollback traces.

## Acceptance evidence

The approved fail-closed slice is complete when the lifecycle suite proves
that valid retained ownership is not erased, unknown ownership never writes,
and corrupt evidence remains inspectable. The wider persistence-hardening item
is complete only when rollback also preserves the last trustworthy obligation.
