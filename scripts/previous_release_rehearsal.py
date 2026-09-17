"""Execute a compatibility case against an extracted known-good release tag."""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = REPOSITORY_ROOT / "scripts" / "fixtures" / "previous_release_setup_case.py"


def _archive(tag: str) -> bytes:
    return subprocess.run(
        ["git", "archive", "--format=tar", tag],
        cwd=REPOSITORY_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout


def rehearse(tag: str) -> None:
    """Extract *tag* and execute the current compatibility case against it."""
    with tempfile.TemporaryDirectory(prefix="heo-rollback-") as temporary:
        checkout = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(_archive(tag)), mode="r:") as archive:
            archive.extractall(checkout, filter="data")
        case_target = checkout / "tests" / "test_previous_release_rehearsal.py"
        shutil.copy2(CASE_PATH, case_target)
        environment = {
            **os.environ,
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
