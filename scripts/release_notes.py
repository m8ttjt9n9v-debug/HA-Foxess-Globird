"""Extract a human-readable GitHub Release title and notes from CHANGELOG.md."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_PATH = REPOSITORY_ROOT / "CHANGELOG.md"
HEADING = re.compile(r"^##\s+(?P<version>[^\s]+)\s+[—-]\s+(?P<title>.+?)\s*$")


def release_text(tag: str, changelog: str) -> tuple[str, str]:
    """Return the GitHub Release title and body for ``tag``.

    A release must have one matching changelog section.  Failing rather than
    publishing generic GitHub-generated notes keeps the HACS version picker
    meaningful and makes a missing release note visible in CI.
    """
    version = tag.removeprefix("v")
    lines = changelog.splitlines()
    for index, line in enumerate(lines):
        match = HEADING.match(line)
        if match is None or match.group("version") != version:
            continue

        end = next(
            (
                candidate
                for candidate in range(index + 1, len(lines))
                if lines[candidate].startswith("## ")
            ),
            len(lines),
        )
        notes = "\n".join(lines[index + 1 : end]).strip()
        if not notes:
            raise ValueError(f"CHANGELOG.md section for {tag} has no release notes")
        return f"v{version} — {match.group('title')}", f"## {match.group('title')}\n\n{notes}\n"

    raise ValueError(f"CHANGELOG.md has no section for release tag {tag}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Release tag, for example v0.12.29rc8")
    parser.add_argument("--title-file", type=Path, required=True)
    parser.add_argument("--notes-file", type=Path, required=True)
    args = parser.parse_args()

    title, notes = release_text(args.tag, CHANGELOG_PATH.read_text(encoding="utf-8"))
    args.title_file.write_text(f"{title}\n", encoding="utf-8")
    args.notes_file.write_text(notes, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
