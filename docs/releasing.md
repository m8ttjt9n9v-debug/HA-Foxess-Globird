# Publishing a HACS release

HACS installs the named `home_energy_orchestrator.zip` asset declared in
`hacs.json`. GitHub records each request for that asset, allowing HACS to show
a Downloads count. The count starts with the first ZIP-based release and
includes both first installations and later updates; it is not a unique-device
count.

For every release:

1. Update the version in both
   `custom_components/home_energy_orchestrator/manifest.json` and
   `pyproject.toml`.
2. Add the matching section to `CHANGELOG.md`.
3. Ensure the commit is on `main` and all required checks pass.
4. Create and push an annotated tag named `v` followed by that exact version.

Pushing the tag runs `.github/workflows/release.yml`. The workflow rejects a
tag that differs from the manifest version, builds a ZIP containing the files
inside `custom_components/home_energy_orchestrator`, verifies that
`manifest.json` and `__init__.py` are at the ZIP root, and creates the GitHub
release with the archive attached.

Do not manually publish the GitHub release before pushing its tag: the workflow
owns release creation so the downloadable asset is present from the start.
