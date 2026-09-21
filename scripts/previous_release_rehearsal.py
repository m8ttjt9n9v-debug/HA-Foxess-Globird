"""Execute a compatibility case against an extracted known-good release tag."""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

from custom_components.home_energy_orchestrator.planner.charge_session import (
    ChargeSessionState,
)
from custom_components.home_energy_orchestrator.planner.ev import (
    DirectEvseReconciliationState,
    SmartSocketRecoveryState,
)
from custom_components.home_energy_orchestrator.planner.ev_learning import (
    DrivingSnapshotState,
)
from custom_components.home_energy_orchestrator.planner.ev_outside_window import (
    PreFreeSessionState,
)
from custom_components.home_energy_orchestrator.planner.ev_persistence import (
    DailyBackfillPersistenceState,
    EvPersistenceState,
)
from custom_components.home_energy_orchestrator.planner.export_session import (
    ExportSessionState,
)
from tests.test_setup import ENTRY_DATA

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = REPOSITORY_ROOT / "scripts" / "fixtures" / "previous_release_setup_case.py"
ENTRY_ID = "phase7-rollback-rehearsal"


def _archive(tag: str) -> bytes:
    return subprocess.run(
        ["git", "archive", "--format=tar", tag],
        cwd=REPOSITORY_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout


def _current_rollback_bundle() -> dict[str, object]:
    """Serialize representative current state for the previous release."""
    recorded_at = datetime(2020, 1, 2, 3, 4, tzinfo=UTC)
    cycle_ready_at = datetime(2020, 1, 2, 8, 0, tzinfo=UTC)
    charge = ChargeSessionState(
        phase="recovering",
        requested_power_kw=7.5,
        attempts=2,
        last_command_at=recorded_at,
    )
    export = ExportSessionState(
        phase="stopping",
        requested_power_kw=9.0,
        attempts=1,
        last_command_at=recorded_at,
    )
    ev = EvPersistenceState(
        restored_at=recorded_at,
        driving_snapshot=DrivingSnapshotState(date(2020, 1, 1), 1234.5),
        daily_driving_energy_kwh=12.5,
        reconciliation=DirectEvseReconciliationState(
            target_current_a=5.0,
            target_limit_percent=82.0,
            attempts=2,
            last_command_at=recorded_at,
            phase="awaiting_feedback",
        ),
        pre_free_session=PreFreeSessionState(True, recorded_at),
        daily_backfill=DailyBackfillPersistenceState(
            cycle_ready_at=cycle_ready_at,
            delivered_kwh=3.25,
            active=True,
            session_target_kwh=8.5,
            session_start_delivered_kwh=1.5,
            frozen_start=recorded_at,
            stop_pending=True,
            stop_attempts=2,
            last_stop_at=recorded_at,
        ),
        charge_to_full_started_at=recorded_at,
        outside_control_active=True,
        smart_recovery=SmartSocketRecoveryState(
            attempted=True,
            phase="fault",
            phase_started_at=recorded_at,
            recovery_current_a=5.0,
        ),
    )
    return {
        "entry_id": ENTRY_ID,
        "entry_version": 6,
        "entry_data": dict(ENTRY_DATA),
        "stores": {
            "charge_session": charge.to_payload(),
            "export_session": export.to_payload(),
            "ev_control": ev.to_payload(),
        },
    }


def rehearse(tag: str) -> None:
    """Extract *tag* and execute the current compatibility case against it."""
    with tempfile.TemporaryDirectory(prefix="heo-rollback-") as temporary:
        checkout = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(_archive(tag)), mode="r:") as archive:
            archive.extractall(checkout, filter="data")
        case_target = checkout / "tests" / "test_previous_release_rehearsal.py"
        shutil.copy2(CASE_PATH, case_target)
        bundle_path = checkout / "phase7-current-rollback-bundle.json"
        bundle_path.write_text(
            json.dumps(_current_rollback_bundle(), sort_keys=True),
            encoding="utf-8",
        )
        environment = {
            **os.environ,
            "HEO_ROLLBACK_BUNDLE": str(bundle_path),
            "PYTHONPATH": os.pathsep.join((str(checkout), str(checkout / "tests"))),
        }
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                str(case_target.relative_to(checkout)),
            ],
            cwd=checkout,
            env=environment,
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v0.12.26")
    args = parser.parse_args()
    rehearse(args.tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
