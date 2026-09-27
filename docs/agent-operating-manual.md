# Agent operating manual

This document gives a new coding task the working discipline needed for this
repository. It is deliberately about *how to work*, not a second source of
truth for HEO behaviour. Policy, configuration and current capability remain
in the documents named by `AGENTS.md`.

## The basic distinction

The repository is the development environment. A designated pilot Home
Assistant installation is controlled staging and acceptance infrastructure. It
is useful for proving a prepared HACS build under real conditions; it is not a
place to edit settings, switch automation off, or improvise a fix while
investigating a problem.

New Codex tasks begin with only the prompt and the repository files they read.
They do not inherit unstated operational knowledge from another conversation.
Read the routing documents in `AGENTS.md`, this manual, relevant recent Git
history, and the current diff before acting. When an instruction is unclear,
keep work in the repository and ask rather than making a live change.

## Default authority boundaries

| Work requested | Default action | What needs explicit user authorisation |
| --- | --- | --- |
| Code, tests, documentation or release preparation | Work in the repository and test there. | Pushing, tagging or publishing if the user did not request it. |
| Live diagnosis | Gather only the requested, read-only evidence. Report facts separately from inference. | Any setting, service call, reload, restart or installation. |
| Pilot validation | Prepare a deployment plan and verify the candidate locally. | The particular site, build, safe time, backup, install/restart and verification steps. |
| Incident recovery | Preserve evidence, identify the known-safe rollback path, and present it. | The exact recovery action on the named site. |

Broad wording such as “check it”, “try it on the pilot” or “fix it” does not
authorise changing live configuration or device state. A user may explicitly
authorise a narrowly defined live action; do only that action and do not treat
it as approval for adjacent experiments.

## Rules for the controlled pilot site

Never use the pilot site as an ad-hoc development box.

- Do not edit `configuration.yaml`, packages, helpers, dashboards, integration
  options or entity values directly as a way to test repository code.
- Do not toggle automatic control, a safety lock, or an automation simply to
  make an investigation easier.
- Do not send FoxESS, EV, smart-socket or Tessie commands as part of diagnosis.
- Do not restart or reload Home Assistant, HACS, or an integration without the
  specific deployment/recovery authority described above.
- Do not replace an installed component from an uncommitted tree or make a
  site-specific patch that is absent from the public, tested package.
- Never describe a site as “fixed” merely because an ad-hoc change temporarily
  stops a symptom.

If the observed live state is unexpected, capture timestamps, relevant entity
states, event/log evidence and the installed version. Then reproduce or
characterise the issue in tests. The next step is a repository change or a
request for a deliberately scoped recovery action—not a workaround on the
pilot.

## Controlled deployment sequence

Use this order when the user has explicitly requested a pilot deployment.

1. **Prepare the candidate.** Identify the exact commit, version and release
   asset. Review the diff, run targeted tests and the relevant wider test suite.
   Confirm no private operational data is in the release.
2. **State the plan.** Record the named target, why it is safe to deploy at
   that time, the preconditions, the backup/rollback method, and the success
   criteria. Device control is out of scope unless separately authorised.
3. **Read current state.** Verify the installed version and relevant gate or
   observer state before touching anything. If the state differs from the
   plan, stop and report it.
4. **Make recovery possible.** Create a recoverable backup of the installed
   component/configuration before install. Do not overwrite the only known-good
   copy.
5. **Install only the released, tested build.** Follow the approved HACS or
   equivalent deployment path. Restart/reload only if it is an authorised part
   of the plan.
6. **Verify safely.** Confirm that Home Assistant and the integration load
   without errors, the expected version is installed, and control remains
   inactive or observer-only unless the user has separately authorised
   activation. Do not manufacture an inverter or EV test event.
7. **Record the result.** Report what was verified, any limitation, and the
   rollback position. Keep private names, addresses, credentials and incident
   evidence out of the public repository.

Activation is a separate decision from installation. A successfully loaded
component is not evidence that an automatic controller is safe to enable.

## Handling incident reports

When a user reports surprising charging, export or device behaviour:

1. Preserve the reported time and distinguish confirmed facts from possible
   explanations.
2. Identify the relevant HEO version, configuration and ownership/gate state
   through read-only evidence if the site is in scope.
3. Check repository history and existing tests for the matching policy path.
4. Add or improve a regression test before proposing a behavioural change.
5. Present a scoped recovery plan if a live action is required; wait for its
   explicit approval.

Never clear histories, toggle gates, restart services or issue device commands
just to obtain a cleaner test condition. Those actions can erase the very
evidence needed to understand the incident.

## Task prompts that preserve this discipline

For a repository-only task, start with a statement like:

> Read `AGENTS.md` and `docs/agent-operating-manual.md`. This is a repository
> task only. Do not inspect, contact or alter any Home Assistant host. Make and
> test the requested change locally, then report the exact commit and evidence.

For an authorised controlled deployment, add the operational boundary:

> The named pilot site may receive this exact released build only. Before
> installing, verify the stated safe preconditions and create the specified
> backup. Do not enable control, alter configuration, or issue FoxESS/EV
> commands. Stop and report if any precondition fails.

This keeps the deployment authority narrow while allowing the task to do useful
preparation and verification work.

## Completion standard

Finish with a factual result: files changed, tests run, exact version or commit
where relevant, and anything that remains unverified. Do not claim that a
controller is safe, a live site is healthy, or an issue is resolved beyond the
evidence actually collected.
