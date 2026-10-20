# Read-only multi-site fleet monitoring

## House and EV power

From v0.12.48, `ev_charging_power_kw`, `house_load_excluding_ev_kw` and
`load_power_reason` are additive attributes on Fleet Summary. Add these three
names to each remote summary REST sensor's `json_attributes` allowlist before
using the new rows in `examples/fleet-dashboard.yaml`. A missing attribute on
an older node is unavailable, not zero. Local cards can read the native summary
directly. No private Tesla helper is required. Both power figures are estimates:
EV power uses actual current with commissioned voltage/phases, not live voltage.

An EV-inclusive mapped load is reduced exactly once. An already EV-exclusive
sensor is not reduced. An explicitly commissioned whole-site balance includes
EV irrespective of the saved sensor-specific flag. For a site with no EV,
EV power is zero and house power is unchanged. Invalid negative source demand
or an impossible subtraction is unavailable; diagnostics retain the raw input.

For external AC solar missing from the inverter's load meter, first verify the
measurement topology. Reconfigure **Solar** to map the measured AC generation
source and its sign; then **House usage and learning → House-load calculation**
offers the normal mapped sensor, fast power balance, or bounded cloud-solar
balance. Review and re-confirm electrical directions after a source change.
Balance = normalized grid import + AC solar generation - battery charging.
Battery discharge and grid export therefore have negative signed values in
that equation. Do not use an inverter's DC PV power as external AC generation.
DC battery readings make this an estimate owing to conversion losses.

Cloud-solar mode is an explicit quality tradeoff, not a repair to CT hardware.
It accepts at most ten minutes since the actual measurement in the explicitly
mapped native SolisCloud AC power frame; Solis may normally update about every
five minutes. HEO reads the already-fetched frame without API calls, matching
its inverter serial, AC power, units and measurement time to the loaded native
entry/device. Equal power (including zero) remains valid when the actual frame
timestamp advances; unchanged/cached HA reports and attribute-only changes
cannot renew it. The supported contract is hultenvp/solis-sensor 4.0.x's
SolisCloud InverterService cache, not a search across integrations or inverters.
An empty cache during fetch/failure, another inverter's frame, mismatched
native value or an unsupported provider is unavailable, never a fallback to a
fresh HA timestamp. If a provider stops producing fresh measurements overnight,
the estimate correctly becomes unavailable; repairing the CT provides continuous
local measurement. Missing, restored,
future, wrong-unit or negative resulting consumption never becomes zero.
Grid/battery/current keep their fast limits; normal EV solar tracking does not
gain the relaxed cloud age. Price-export checks use the explicit house bound,
keep independent local grid/battery/SoC freshness, and clean up on expiry.

Existing learning and controller storage are unchanged. Upgrading does not
select a source or change policies. A normal mapped-source downgrade is
storage-compatible. Before downgrading a site using power balance, commission a
known-valid mapped house source (or repair its CT) and explicitly select Sensor:
older releases ignore the new option and may accept the original bad meter.
Do not silently return a broken source to automatic control during rollback.

Always fetch and back up the latest live dashboard before applying only the
approved row changes. Never replace a personal dashboard from this example.

HEO exposes `sensor.home_energy_fleet_summary` as a compact monitoring payload.
Its state is the commissioned orchestrator mode and its attributes contain the
small set of power, plan, financial, scorecard, and learning values useful on a
central dashboard. The entity exposes no actions and has no control authority.

One Home Assistant instance can poll that entity from other sites using Home
Assistant's built-in RESTful Sensor integration. A monitoring-hub failure or
network outage therefore cannot change remote-site operation.

## Remote sites

Create a dedicated non-administrator Home Assistant user at each remote site
and create a long-lived access token from that user's profile. Home Assistant
tokens inherit their user's permissions; they are not intrinsically read-only.
The configuration below nevertheless performs only an HTTP `GET` for one
sensor state. Keep every token in the hub's `secrets.yaml` and never commit it.

## Monitoring hub

Store the complete bearer values in `secrets.yaml`:

```yaml
site_b_fleet_token: "Bearer REPLACE_WITH_SITE_B_TOKEN"
site_c_fleet_token: "Bearer REPLACE_WITH_SITE_C_TOKEN"
```

Add the following to a package such as `packages/heo_fleet.yaml`, replacing the
host placeholders with private Tailscale names or addresses. Specify port 8123
exactly once.

```yaml
rest:
  - resource: "http://SITE_B_PRIVATE_HOST:8123/api/states/sensor.home_energy_fleet_summary"
    scan_interval: 60
    timeout: 10
    headers:
      Authorization: !secret site_b_fleet_token
      Content-Type: application/json
    sensor:
      - name: "Site B Fleet Summary"
        unique_id: heo_fleet_site_b
        value_template: "{{ value_json.state }}"
        json_attributes_path: "$.attributes"
        json_attributes: &heo_fleet_attributes
          - summary_schema_version
          - battery_soc
          - battery_power_kw
          - grid_power_kw
          - solar_power_kw
          - house_load_kw
          - sellable_energy_kwh
          - planned_export_kwh
          - orchestrator_status
          - foxess_control_gate
          - charging_status
          - export_status
          - ev_control_status
          - forecast_cost
          - measured_cost
          - latest_actual_cost
          - forecast_error
          - zerohero_status
          - latest_zerohero_status
          - forecast_scorecard_status
          - house_learning_samples
          - ev_learning_samples
          - ledger_status
          - tariff_status
          - last_update

  - resource: "http://SITE_C_PRIVATE_HOST:8123/api/states/sensor.home_energy_fleet_summary"
    scan_interval: 60
    timeout: 10
    headers:
      Authorization: !secret site_c_fleet_token
      Content-Type: application/json
    sensor:
      - name: "Site C Fleet Summary"
        unique_id: heo_fleet_site_c
        value_template: "{{ value_json.state }}"
        json_attributes_path: "$.attributes"
        json_attributes: *heo_fleet_attributes
```

The YAML anchor is local to this package and prevents the attribute list from
being duplicated. Run **Check configuration** before restarting the hub. An
HTTP 404 after otherwise valid configuration normally means the remote site
has not yet installed the HEO release containing the Fleet Summary entity.

Dashboard cards can read values directly with templates such as:

```jinja2
{{ state_attr('sensor.site_b_fleet_summary', 'battery_soc') }}
```

Treat an unavailable summary, or a `last_update` older than the expected poll
interval plus a reasonable grace period, as a monitoring warning. Do not use a
remote summary as a control input.

## Installed HEO version

The reusable Fleet dashboard includes an **Installed HEO** row for each site.
It reads these optional, read-only hub sensors:

| Site card | Version sensor on the hub |
| --- | --- |
| Local site | `sensor.fleet_site_alpha_heo_version` |
| Remote site 1 | `sensor.fleet_site_bravo_heo_version` |
| Remote site 2 | `sensor.fleet_site_charlie_heo_version` |

Use the HEO HACS update entity's **`installed_version` attribute**, not its
`latest_version` attribute or its `on`/`off` state. Those describe the release
available to install and whether an update is available, respectively. The
Fleet Summary payload does not currently contain a software version. Confirm
each site's HEO update entity ID in Developer Tools; it can differ or have
been renamed. Do not select another integration's update entity.

For the local site, a template sensor can expose that attribute. The entity ID
below is an example; replace it with the verified HEO HACS update entity:

```yaml
template:
  - sensor:
      - name: Fleet Site Alpha HEO Version
        unique_id: fleet_site_alpha_heo_version
        availability: >-
          {% set e = 'update.home_energy_orchestrator_update' %}
          {% set v = state_attr(e, 'installed_version') %}
          {{ states(e) in ['on', 'off']
             and v is string and v | trim not in ['', 'unknown', 'unavailable', 'none'] }}
        state: "{{ state_attr('update.home_energy_orchestrator_update', 'installed_version') }}"
```

For each remote site, add a separate GET to the existing monitoring package,
using that site's existing dedicated monitoring token. For example:

```yaml
rest:
  - resource: "http://SITE_B_PRIVATE_HOST:8123/api/states/update.home_energy_orchestrator_update"
    scan_interval: 60
    timeout: 10
    headers:
      Authorization: !secret site_b_fleet_token
      Content-Type: application/json
    sensor:
      - name: Fleet Site Bravo HEO Version
        unique_id: fleet_site_bravo_heo_version
        availability: >-
          {% set attrs = value_json.get('attributes', {}) if value_json is mapping else {} %}
          {% set v = attrs.get('installed_version') if attrs is mapping else none %}
          {{ value_json is mapping
             and value_json.get('state') in ['on', 'off']
             and v is string and v | trim not in ['', 'unknown', 'unavailable', 'none'] }}
        value_template: "{{ value_json.attributes.installed_version }}"
```

Repeat with the other remote site's host, token, update entity and `Charlie`
sensor name. Merge these entries into the existing `template` and `rest`
lists; do not create duplicate top-level YAML keys or replace the live package.
Check configuration before applying changes. Confirm the created entity IDs
match the dashboard; existing registry names can affect the final ID.

The version row shows **—** when its source is missing or unavailable, including
a failed remote poll; it must not substitute the latest release or a manually
hard-coded version. The remote value reflects the last successful poll, normally
within 60 seconds. A cached version is not proof a site is online: keep the
Fleet Summary's availability and `last_update` checks alongside it.

This is the version **installed by HACS**, not a guarantee that Home Assistant
has restarted and loaded that code. A pending restart may leave the previous
version running. The monitoring sensors do not install, reload, restart or
change any HEO or device controls, and they also work with older HEO releases
that already have a HACS update entity.
