# Read-only multi-site fleet monitoring

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
