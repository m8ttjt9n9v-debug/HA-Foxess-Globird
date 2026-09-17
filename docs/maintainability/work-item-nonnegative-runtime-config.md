# Work item — strict non-negative runtime configuration

## Problem and evidence

Seventeen tariff, allowance, site and inverter values shared a generic helper
that reread the mutable configuration mapping. Its important compatibility
contract distinguished missing keys from invalid configured values.

## Existing contract

- A missing key uses the caller's established default.
- A valid finite non-negative configured value is returned unchanged.
- Malformed, negative, `NaN` and infinite values invalidate the calculation.
- Unknown compatibility keys retain the caller-supplied default.

## Invariants and non-goals

- Preserve every default and invalid-configuration outcome.
- Preserve accounting, ZEROHERO, tariff, site and inverter calculations.
- Do not change automation policy, persistence or hardware commands.

## Deliverables

- Parse the complete 17-key contract once into an immutable strict snapshot.
- Make the coordinator compatibility bridge consume only that snapshot.
- Characterize every key across missing, valid and invalid inputs.

## Outcome

- All 17 values now use the immutable strict snapshot.
- Focused configuration, setup, lifecycle, ledger, tariff and manual-diagnostic
  tests: 212 passed.
- Raw runtime configuration reads fell from two to one.
- Complete regression suite: 623 passed.
- Ruff, all generated/frozen contracts and the v0.12.26 previous-release
  rehearsal passed.
