# Changelog

All notable changes to this project are documented in this file.

## [0.2.0] - 2026-06-25

### Added

- Official Docker image published to GHCR (`ghcr.io/open-dpm/dpm`); the GitLab CI template can use it via `DPM_IMAGE` to skip `pip install` on every run
- Optional `build:image` job (kaniko) to build the image into your own GitLab Container Registry
- Status badges in the README (CI, license, Python, release, Telegram)

### Changed

- README rewritten problem-first, with a merge-request-gate flow diagram and a security/privacy section
- GitLab setup guide: clearer `DPM_PKG` variable instructions and a section on faster CI with a prebuilt image

## [0.1.0] - 2026-06-23

Initial public release.

### Added

- Data Product Manifest format — a multi-file definition of a data product: schema,
  semantics, quality rules, SLA, physical layout, runbook and ownership
- CLI: `dpm validate`, `validate-rules`, `governance`, `breaking-changes`, `suggest-version`
- Validators for manifest structure, quality rules, governance requirements, SemVer bumps
  and Avro breaking-change detection
- Example data product (`examples/aviation/flights`) and templates for new manifests
- Reusable GitLab CI template and GitHub Actions workflow; ruff and mypy configuration
- Guides: GitLab mirror setup and a data steward guide; data governance specification
