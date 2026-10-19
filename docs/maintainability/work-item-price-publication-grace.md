# Price-export publication-gap correction

## Approved policy change

The v0.12.46 controller deliberately ended price permission at every block
boundary. Delayed publication then forced cleanup/readmission during sustained
high prices. The approved correction permits last-confirmed evidence until
interval end plus 150 seconds, and newer confirmed high blocks renew a still-
live session without a stop. This is a narrow policy correction, not a refactor
or new market writer. Current-price sensors retain exact-interval semantics.

## Invariants and compatibility

- No change to ordinary ZEROHERO latching, EV control or charge priority.
- Current Sellable, house/EV protection, battery reserve/floor, daily cap,
  electrical freshness, native units, Safety Lock and original actuators bind
  every continuing/renewed price session. Renewals cannot raise latched power.
- Failures, duplicate/older reports and estimates never advance interval expiry.
  Fresh low prices and affirmative market restrictions withdraw permission now.
- Only a newer accepted permission boundary renews an unexpired starting/active
  session; the same block cannot extend a resource-shortened deadline.
- No new entities, config keys, service, authentication or poller. No automatic
  activation or dashboard writes. The optional `price_permission_end` journal
  addition is documented separately; old price payloads and exact four-field
  ordinary payloads remain readable. Diagnostic history never restores the
  volatile last-confirmed bridge. Restart cleanup precedes fresh readmission.

## Validation

New real-HA lifecycle regressions first failed against strict expiry. They now
exercise twenty minutes of sustained high prices with 120-second report gaps;
immediate fresh-low stop at six points during grace; the exact 150-second
deadline, failed fetches and repeated old reports; a late cancelled callback;
expiry without an operator reconcile; restart during grace; electrical source
loss; and market restrictions followed by failed fetches. Pure policy tests
cover cap/resource shrinkage, same-block non-renewal, no revival after expiry,
and optional payload round-trip/rejection. Existing Amber correction, source
priority, command-staging, manual/Safety Lock, setup/reload and replay cases
remain required. The complete frozen suite, Ruff and v0.12.46/v0.12.26
upgrade/rollback rehearsals gate publication; GitHub checks and exact published
asset verification gate separately authorised pilot deployment.

Local evidence for this candidate: 3,301 tests pass, Ruff passes, and both
v0.12.46 and frozen v0.12.26 upgrade/rollback rehearsals pass. These are
repository checks, not a claim of live-site acceptance or physical export.

## Rollback and acceptance boundary

Retain the previous release and verified recovery backup. Do not downgrade an
active/unconfirmed price session: first deliberately withdraw the request and
verify completed cleanup while write authority exists. Publication and local
tests are not physical spike delivery or retailer-payment evidence. Controlled
pilot acceptance remains separate; no synthetic live export is authorised by
this correction.
