# Changelog

## 0.1.2 — Validation correction

- Fix two setup-flow formatting violations so the repository's GitHub Actions
  lint job completes successfully.

## 0.1.1 — Deployable observer release

- Rename the public integration to **FoxESS Globird Energy Observer**.
- Allow optional house-load and EV state-of-charge entity selectors to be
  left blank during setup.
- Validate the package in a clean Home Assistant OS pilot and with the HACS
  GitHub Action.

## 0.1.0 — Observer release

- Initial HACS custom-integration package.
- Guided entity mapping with no YAML edits required.
- Normalised, observer-only energy ledger and diagnostics.
- No actuator services are called by this release.
- Added setup, reconfiguration, live-update, unload, and no-service-call tests
  using the Home Assistant test harness.
