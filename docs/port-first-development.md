# Port-first development guide

This project extends a proven Home Assistant system. It is not a greenfield
controller. Complexity in the source is evidence to understand, not permission
to replace it with a simpler or more elaborate new algorithm.

## Required workflow

1. **Recover context.** Read `AGENTS.md`, `docs/source-of-truth.md`,
   `ROADMAP.md`, this guide, relevant policy documents, recent Git history, and
   the current diff. Never rely on conversation memory alone.
2. **Inventory the source.** Identify the Working Single Phase Pilot Site entities, helpers,
   automations, triggers, timing, persistent latches, failure behavior, and
   service calls involved in the requested feature.
3. **Write a provenance table.** Map each source input, calculation, branch,
   state transition, and output to its proposed HEO equivalent. Mark site facts
   separately from algorithm rules.
4. **Characterize before changing.** Add golden test vectors for the existing
   behavior, including boundaries, restart, outage, stale input, manual
   override, and competing-owner cases.
5. **Port mechanically.** Preserve decisions and sequencing. Refactoring into
   Python types is welcome only when the observable behavior remains mapped.
6. **Prove parity.** Review the provenance table and golden tests. A green suite
   proves only its assertions; it is not by itself evidence of parity.
7. **Extend through configuration.** Add arbitrary phase/service/inverter/EV
   capabilities as a separate layer. Run both original-site and extension
   scenarios against the same policy core.
8. **Expose cautiously.** Do not advertise, enable, or deploy a controller until
   telemetry coherence, ownership, restart, recovery, and rollback are tested.
9. **Record the result.** Update source-of-truth, roadmap, requirements,
   changelog, and user-facing capability claims in the same commit.

## Prohibited shortcuts

- Rewriting an existing algorithm from a verbal summary.
- Treating additional phases or higher service limits as a reason for a new
  controller instead of a configurable extension.
- Hardcoding site times, phases, current, voltage, power, energy, tariff values,
  entity IDs, or device brands into policy logic.
- Auto-discovering an actuator or inferring physical topology from a transient
  reading.
- Keeping safety latches or learning-cycle state only in process memory.
- Allowing cloud and Modbus owners to overlap because their named windows do
  not overlap.
- Claiming a control gate proves no other automation can write.
- Preserving dead code or misleading sensors to make a removed feature appear
  present.

## Review template

Every control pull request or commit description must answer:

- Which Working Single Phase Pilot Site source lines and observed behavior are being ported?
- Where is the provenance table?
- Which changes are parity work and which are site extensions?
- What values became configuration rather than literals?
- How are inputs timestamped and checked for coherent freshness?
- What survives restart, and what happens after an outage exceeding the gap?
- How is exclusive ownership enforced and independently observed?
- Which tests cover original Working Single Phase Pilot Site behavior and each target topology?
- What disables the feature and restores a known-safe state?
- Which documents and roadmap boxes changed?

If those answers cannot be produced, keep the feature observer-only or leave it
on the roadmap.
