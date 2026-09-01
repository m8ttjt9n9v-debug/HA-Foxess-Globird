# HACS publication checklist

This project is not ready to be offered through HACS until the custom-repository
items below are complete. A local archive and passing local tests are useful
pilot evidence; neither creates a public HACS distribution.

## Repository work already included

- The integration is packaged below `custom_components/home_energy_orchestrator`.
- `hacs.json` is in the repository root and declares the supported Home
  Assistant version.
- The integration has a mandatory `brand/icon.png` and a translated UI flow.
- HACS validation and Hassfest workflows are committed under `.github/workflows`.
- Automated tests check the local package layout and metadata so these
  requirements do not silently regress.

## Custom-repository release gate

1. Publish `m8ttjt9n9v-debug/HA-Foxess-Globird` as a public GitHub repository. HACS
   only supports public GitHub repositories.
2. The manifest identifies `@m8ttjt9n9v-debug` as code owner and links to that
   repository for documentation and issues.
3. Set the GitHub repository description, enable issues, add a clear README,
   and apply the relevant topics.
4. The integration is scoped to Australia and declares `"country": "AU"` in
   `hacs.json`.
5. Push the repository to GitHub and make the HACS validation and Hassfest
   actions pass with no errors or ignored checks. This is this project's
   release gate.

GitHub releases are preferred by HACS for custom repositories but are not
required: without one, HACS uses the default branch.

## Publication boundary

Only after the preceding evidence exists should the integration be offered as
a HACS custom repository. Default-repository inclusion is a separate HACS
review process: it additionally requires a full GitHub release after the
HACS and Hassfest actions pass, followed by a submission to the HACS default
repository.
