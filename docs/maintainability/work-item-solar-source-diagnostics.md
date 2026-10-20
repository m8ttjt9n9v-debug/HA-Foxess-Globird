# Work item: explain a rejected native solar source

The optional cloud-solar balance can reject a source with only the generic
`source_unavailable` result. That is safe but insufficient to distinguish a
native binding, cache-shape, unit, timestamp or value mismatch.

The existing capture function now optionally fills a small diagnostic mapping
from those SAME synchronous branches. Normal callers receive the identical
TelemetrySource result. HEO's existing diagnostics download requests this
mapping only for the explicitly selected cloud-solar profile.

No controller, source acceptance, timestamp, permission, stored payload, entity,
provider request or polling schedule changes. An accepted cache shape still
needs the existing age/coherence checks. Unknown metadata does not become zero.
Only fixed validation reasons, known field presence/primitive types, identity
match booleans and finite numeric power/timestamp evidence may leave the
adapter. Serial, entity/entry/device identity, URLs, arbitrary cache keys and
credentials are omitted. Malformed numbers remain JSON-safe.

Regressions compare capture with and without diagnostics under missing fields,
binding/provider/unit/value/type failures, stale measurements, and sensitive
extra cache content. Setup covers opt-in projection without service calls.
The final versioned suite passes 3,477 tests, full-tree Ruff and v48/v26
upgrade/rollback rehearsals. The independently reviewed EV-ack correction is
recorded separately; no further control seam is changed for diagnostics.

Rollback ignores this additive diagnostic section and reads unchanged storage.
Publication and each controlled live acceptance remain separate. This report
does not itself fix a native-provider compatibility issue or prove physical
energy delivery.
