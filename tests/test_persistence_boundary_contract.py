"""Phase 5 typed persistence-boundary tests."""

from scripts.persistence_boundary_contract import validate_persistence_boundary


def test_all_production_store_io_uses_typed_repositories() -> None:
    validate_persistence_boundary()
