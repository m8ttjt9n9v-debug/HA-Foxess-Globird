"""Phase 7 active-controller and pure-planner boundary tests."""

from scripts.controller_boundary_contract import validate_controller_boundary


def test_controllers_and_planners_retain_their_platform_boundaries() -> None:
    validate_controller_boundary()
