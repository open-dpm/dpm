# Changelog

All notable changes to this project are documented in this file.

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
