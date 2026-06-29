# Changelog

All notable changes to this project are documented in this file.

## [0.1.0] - 2026-06-29

Initial public release.

### Added

- Data Product Manifest format — a multi-file definition of a data product: schema (Avro),
  semantics, quality rules, SLA, physical layout, runbook and ownership
- CLI: `validate`, `validate-rules`, `governance`, `breaking-changes`, `suggest-version`,
  `validate-conformance`, `conformance-impact`
- Validators for manifest structure, quality rules, governance requirements, SemVer bumps
  and Avro breaking-change detection
- Enterprise Data Model (EDM) conformance: canonical entities as versioned contracts
  (`kind: canonical_entity`), opt-in `metadata.conforms_to` with rename mapping, and a
  conformance check that a product carries every mandatory canonical attribute with a
  compatible, non-nullable type; `conformance-impact` lists the products conforming to an
  `entity@major`
- `kind`-aware validation: canonical entities skip the SLA / quality-rules / lineage / PII
  requirements that only apply to row-bearing data products
- Example data product (`examples/aviation/flights`) conforming to a canonical entity
  (`examples/canonical/aircraft_observation`), plus templates for new manifests and entities
- Docker image published to GHCR; reusable GitLab CI template and GitHub Actions workflow;
  ruff and mypy configuration
