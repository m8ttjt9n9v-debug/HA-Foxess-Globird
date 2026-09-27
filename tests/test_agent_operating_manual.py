"""Keep the task-level live-site safety boundary discoverable."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_agents_routes_live_site_work_to_operating_manual() -> None:
    agents = (REPOSITORY_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "docs/agent-operating-manual.md" in agents
    assert "controlled staging" in agents
    assert "explicit user authorisation" in agents


def test_operating_manual_forbids_ad_hoc_pilot_mutation() -> None:
    manual = (REPOSITORY_ROOT / "docs" / "agent-operating-manual.md").read_text(
        encoding="utf-8"
    )

    assert "Never use the pilot site as an ad-hoc development box" in manual
    assert "Do not toggle automatic control" in manual
    assert "Do not send FoxESS, EV, smart-socket or Tessie commands" in manual
    assert "Activation is a separate decision from installation" in manual
