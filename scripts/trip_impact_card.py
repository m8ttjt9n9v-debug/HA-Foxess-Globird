"""Shared read-only trip-impact presentation for native and legacy dashboards."""

from __future__ import annotations

TRIP_IMPACT_CONTENT = """\
{% set raw = state_attr('sensor.home_energy_trip_charge_status', 'energy_impact') -%}
{% set impact = raw if raw is mapping else {} -%}
{% set free_start = as_datetime(impact.get('until_free_start'), none) -%}
{% set values = namespace(valid=true) -%}
{% for field in ['pack_energy_kwh', 'wall_energy_kwh', 'before_free_kwh',
    'during_free_kwh', 'after_free_kwh', 'battery_available_for_ev_kwh',
    'battery_contribution_kwh', 'extra_paid_energy_kwh', 'cost_min', 'cost_max'] -%}
  {% set value = impact.get(field) -%}
  {% if value is boolean or value is not number or not is_number(value) -%}
    {% set values.valid = false -%}
  {% elif value < 0 -%}
    {% set values.valid = false -%}
  {% endif -%}
{% endfor -%}
{% if impact.get('status') == 'already_at_target' -%}
The car is already at the selected trip target. No extra trip charging is currently needed.
{% elif impact.get('status') == 'estimated' and values.valid
    and impact.get('scope') == 'before_next_free_window_only'
    and impact.get('cost_min') <= impact.get('cost_max') -%}
{% set low = '$%.2f' | format(impact.cost_min) -%}
{% set high = '$%.2f' | format(impact.cost_max) -%}
{% set cost = low if impact.cost_min == impact.cost_max else low ~ '–' ~ high -%}
**Extra cost before free power: {{ cost }}**
{% if impact.get('source') == 'legacy' %}
Estimate uses your existing trip helpers.
{% endif %}
{% if free_start is not none %}
Until free power starts **{{ as_local(free_start).strftime('%a %d %b, %H:%M') }}**.
{% endif %}

- Energy needed: **{{ '%.1f' | format(impact.wall_energy_kwh) }} kWh**, including charging losses.
- Charging before free power: **{{ '%.1f' | format(impact.before_free_kwh) }} kWh**.
- House battery available for the car:
  **{{ '%.1f' | format(impact.battery_available_for_ev_kwh) }} kWh**,
  after expected house use and the configured minimum battery level. Expected trip use:
  **{{ '%.1f' | format(impact.battery_contribution_kwh) }} kWh**.
- Extra paid energy before free power: **{{ '%.1f' | format(impact.extra_paid_energy_kwh) }} kWh**.
{% if impact.during_free_kwh > 0 or impact.after_free_kwh > 0 %}
The rest of this trip charge: **{{ '%.1f' | format(impact.during_free_kwh) }} kWh during** and
**{{ '%.1f' | format(impact.after_free_kwh) }} kWh after** the next free window.
Later charging costs are not estimated from the current house battery.
{% endif %}
This is extra cost **only until the next free window**, not the total trip cost.
Paid energy includes house power moved onto the grid by using its battery for the car.
No future solar or export forecast is included.
Supply charges, lost export earnings and the ZEROHERO credit are excluded.
House use, inverter limits, battery protection and slower charging near full can change the result.
{% elif impact.get('status') == 'out_of_scope' -%}
A before-free cost estimate does not apply to this trip's current timing.
This does not mean the whole trip will be free.
{% elif impact.get('reason') == 'trip_paused' -%}
The trip is paused. The estimate will update when charging resumes.
{% elif raw is not mapping -%}
The trip energy estimate is not available.
This card needs an HEO version that provides trip energy-impact data.
{% else -%}
The trip energy estimate is not available yet.
Check the trip plan and its required energy and tariff inputs.
{% endif %}
"""


def build_trip_impact_card() -> dict:
    """Format the canonical HEO projection without another energy/cost calculation."""
    return {
        "type": "markdown",
        "title": "Estimated trip impact",
        "content": TRIP_IMPACT_CONTENT,
    }
