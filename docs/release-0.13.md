# 0.13 consolidation release candidate

The proposed stable version is **0.13.0**. Local **0.13.0rc1** combines the
post-v0.12.62 candidate line for controlled qualification. It is not published
or automatically installed. The roadmap leaves 1.0 readiness subject to
sustained system trials and independently proven hardware combinations.

## Included behaviour

| Area | Combined correction |
| --- | --- |
| EV retries | Independent current, limit and start episodes; persistent timing; measured override qualification; restart/reconnect handling. |
| Normal EV target | Apply the configured target consistently. 90% is the default; normal 100% remains distinct from paid Charge to Full. |
| Dynamic reservation | One protected pool, original measurement clocks, last-known-SoC/timed-outage choices and separate physical evidence. |
| House learning | Qualified unplugged/zero-draw collection, raw/protected progress, coverage gaps, retention and compatible restart; unchanged reserve formula. |
| Free-energy allowance | Measured daily cutoff and existing outside-policy/Self Use handoff; independent Full override. |
| Afternoon solar soak | Optional maximum mode with 95/90 defaults, configured hysteresis and existing inverter percentage and energy/current limits. |
| Lifecycle guards | Durable measured recovery, ceiling-bounded release, sleeping-vehicle planning, original-mode binding and current electrical evidence across awaited work. |

The changes share existing controllers and stores. No extra writer, poller,
allocator, tariff assumption or site-specific limit is added. Saved operator
choices remain authoritative; maximum mode defaults off.

## Lifecycle provenance and stability

The retained pilot's export/recovery sequencing and existing Dynamic extension
remain the source. Mechanically reconcile the previously qualified repository
lifecycle correction with current normal-target and unavailable-SoC choices.

| Existing decision or state | Retained implementation and guard |
| --- | --- |
| Protected export pool and Fixed bounded latch | Keep arithmetic and Fixed's original fallback; mode changes withdraw old intent through the existing reducer. |
| Version-one export session | Persist optional original reservation-mode binding. Idle clears it; old payloads remain readable. |
| Canonical electrical normalization | Requalify configured raw grid/battery evidence before positive writes, including source loss before a coalesced refresh. Unconfigured optional mappings remain optional. |
| Reducing cleanup | Retain zero-power/Self Use restoration and pending acknowledgement after authority loss. |
| EV recovery journal | A read-only SoC lookup cannot complete pending recovery. Only the existing measured checkpoint can release it. |
| Configured normal target | Bound Dynamic minimum/release by the normal target; retain Fixed semantics and saved preferences. |
| Sleeping/retained planning | Respect the chosen planning/outage policy without acknowledging physical stops or granting current/handoff authority. |

These strict command-time checks address withdrawn permission, not sensor
noise. They add no switching threshold or grace timer. Invalid, expired or
rebound evidence withdraws immediately; normal reconciliation can use restored
valid evidence. The configured recovery buffer retains its existing band.

## Upgrade and rollback

Keep the domain, configuration-entry version 6, version-one stores and registered
identities. Retain settings, completed learning/driving evidence and compatible
pending duties. Optional fields do not justify clearing history or journals.

An older reader may ignore optional fields and restore its older policy.
Rollback does not preserve new functionality. Legacy unbound active export
cannot prove its historical mode after an ambiguous failed adoption/concurrent
mode edit. Begin controlled upgrades idle or verify durable current binding
before permitting mode edits; guessed provenance cannot authorise power.

The ZIP contains committed integration files with `manifest.json` and
`__init__.py` at its root. It excludes local notifications/recipients and
third-party integration patches. Existing dashboards stay unchanged; reusable
examples require deliberate import/merge against a fresh live layout.

## Limits and remaining release gates

Local regression qualification covers 6,126 collected cases. The full run
passed 6,117; nine older fixture expectations required correction. All three
affected files then passed their 93 cases, retaining the configured boundaries,
durable checkpoint and physical-source assertions. Production hashes remained
unchanged between runs. Ruff, ten configuration/entity/persistence checks and
both directions of compatibility with v0.12.26 and v0.12.62 pass locally.
The qualification record retains the original failures and focused reruns;
this is not a claim that the initial full run was entirely green.

Do not claim fixes for upstream vehicle current mismatches, guaranteed zero
grid import, shorter explicit-stop retry backoff, concurrent discretionary EV
charging/forced export, high-current resets, journey prediction or Extended
Away. Local regression evidence is separate from physical and tariff acceptance.

Freeze the exact commit, archive and hashes. Run full regression, lint and
contracts plus bidirectional rehearsals against v0.12.26 and the stable
baseline; dedicated lifecycle/learning/retry/soak tests supplement that general
rehearsal. Hosted workflow/HACS checks, controlled acceptance, the selected
settling interval and explicit publication authority precede stable release.
The 48-hour preference runs from the final control-code change. It creates no
publishing, monitoring or additional deployment job.
