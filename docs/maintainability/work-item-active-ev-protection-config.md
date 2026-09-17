# Work item — typed automatic-export EV protection inputs

## Scope

Add one immutable EV connection/electrical input group and migrate only the
automatic export controller's mandatory connected-EV keepalive calculation to
that group.

## Existing contract

- A site without configured and commissioned EV control protects zero EV
  energy, even if retained/default EV values remain in the config entry.
- A commissioned positive baseline without explicit home and cable mappings,
  or without readable mapped states, fails closed with an unknown reservation.
- A vehicle not confirmed home and connected protects zero energy.
- A confirmed connected vehicle protects
  `hours × baseline amps × voltage × phases / 1000` kWh.
- Numeric parsing retains existing defaults and clamps negative legacy values
  to zero.

## Invariants and non-goals

- Preserve every return value and fail-closed branch of the keepalive method.
- Preserve export planning, request power, window timing and command ordering.
- Do not migrate the active EV charging controller in this work item.
- Do not change serialized fields, defaults, validation or config-entry version.

Rollback requires only reverting this code; persisted configuration and session
payloads are unchanged.

## Outcome

The automatic FoxESS controller now has zero direct constant-key raw mapping
reads. Total direct runtime raw reads fell from 86 to 81; the corresponding EV
fields are parsed once at the configuration boundary. Generic numeric reads in
other controller policy paths remain outside this work item.

Validation completed with 515 tests, repository-wide Ruff, configuration and
persistence contracts, and the unmodified v0.12.26 previous-release rehearsal.
