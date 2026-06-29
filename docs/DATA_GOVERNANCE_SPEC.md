# Data Governance Specification

This document describes the governance model DPM enforces for data products. It is
the human-readable companion to the validators in `src/dpm/validators/`: every rule
below is checked automatically in CI.

## Scope and intent

DPM governs **data products as code**. A data product is described by a manifest and
its supporting files, versioned in Git, and changed only through reviewed merge
requests. Governance is enforced at change time (in CI), not at data runtime — DPM
validates the *contract*, it does not read or modify the underlying data.

## Roles

| Role | Responsibility | Where it lives |
|------|----------------|----------------|
| **Owner** | Accountable for the product: definition, SLA, lifecycle. | `metadata.owner` (`team`, `email`, optional `mattermost`, `on_call`) |
| **Steward** | Maintains quality rules, semantics and lineage day to day. | A member of the owning team; reviews via `CODEOWNERS` |
| **Custodian** | Operates the pipeline/storage that produces the data. | Producer system in `metadata.systems`; runbook owner |
| **Reviewer** | Approves changes to a product. | `CODEOWNERS` for the product directory |

Changes to a product directory should be approved by a handle listed in that
directory's `CODEOWNERS`. Enforcement of *who* and *how many* approvers is expected to
come from your platform's approval rules. DPM ships an optional CODEOWNERS approval
check (`dpm.codeowners.check_mr_approvals`, enabled with `DPM_ENFORCE_CODEOWNERS=true`)
for setups that have no such gate — leave it off when your platform already enforces
approvals.

## The governed manifest

Each product lives in its own directory with these files:

- `manifest.yaml` — index: `kind` (`data_product`, default, or `canonical_entity`),
  `spec_version`, `manifest_version`, `status`, `metadata`, references to the files below,
  `lineage`, `changelog`.
- `schema.avsc` — Avro schema (the source of truth for fields).
- `semantics.yml`, `quality_rules.yml`, `sla.yml`, `physical_layout.yml`, `runbook.md`.
- `CODEOWNERS` — reviewers for the directory.

## Rules enforced in CI

Validators emit findings at one of three severities: **error** (blocks merge),
**warning** (surfaced, non-blocking) and **info**.

### Structure and versioning
- `spec_version` and `manifest_version` are present; `manifest_version` follows SemVer
  (`version_spec`, `version_manifest`, `version_semver`).
- `status` is one of `draft | active | deprecated | retired`.
- `data_category` is one of `transactional_data | master_data | reference_data | analytical_data`.

### Ownership
- `metadata.name`, `namespace`, `description`, `owner` are present (`metadata_required`).
- `owner.team` and `owner.email` are present (`owner_required`).
- Tags exist for discoverability (`metadata_tags`, warning).

### Privacy (PII)
- `metadata.pii` is a required boolean (`pii_flag`).
- It must be consistent with the schema: `pii: false` with a field annotated
  `"pii": true` is an error (`pii_conflict`); `pii: true` with no annotated field is a
  warning (`pii_unmarked_fields`).
- **PII annotations are declarative metadata** for downstream systems (masking, access
  control, retention). DPM records and validates them; it does **not** enforce them and
  makes no compliance guarantee. Jurisdiction-specific requirements belong in your own
  downstream pipelines.

### References and lineage
- Referenced `schema`, `quality_rules` and `sla` files exist (`schema_reference`,
  `schema_exists`, `quality_rules_reference`, `sla_reference`).
- `lineage` declares upstream and downstream; `lineage.downstream` is a list.
- `changelog` has at least one entry and its latest version matches `manifest_version`.

### Critical products
Products tagged `critical` or `tier-1` additionally require an `on_call` link, a
`runbook.md` and at least one declared downstream consumer.

### Canonical model conformance (EDM)
A product may opt in to the Enterprise Data Model by declaring the canonical entities it
represents (`metadata.conforms_to: [{entity: "name@MAJOR", rename: {...}}]`). For each one,
`dpm validate-conformance` resolves the entity from the canonical registry and requires the
product schema to carry every **mandatory** canonical attribute (the entity's non-nullable
fields), under its physical name, with a compatible, non-nullable type
(`conformance_missing_attribute`, `conformance_type_mismatch`, `conformance_nullable_attribute`).
A product without `conforms_to` is outside the EDM and is not checked. Canonical entities
themselves are manifests with `kind: canonical_entity` — definitions without rows, so the SLA,
quality-rules, lineage and PII rules above do not apply to them. This is conformance to a shared
entity model (DMBOK Enterprise Data Model), distinct from the referential-integrity `reference`
quality rule. Full workflow: [canonical-model.md](canonical-model.md).

## Data quality dimensions

`quality_rules.yml` rule types map to standard quality dimensions:

| Dimension | Rule types |
|-----------|------------|
| Completeness | `not_null`, `completeness` |
| Validity / conformity | `regex`, `enum`, `range`, `format` |
| Uniqueness | `unique` |
| Timeliness | `freshness`, `currency` |
| Consistency / integrity | `custom`, `sql`, `reference` |
| Reasonableness | `reasonableness` |

Accuracy (agreement with the real world) cannot be asserted from a contract and is out
of scope for DPM.

## Versioning and change management

- **MAJOR** — breaking change (field removed, type narrowed, a required field added).
- **MINOR** — backward-compatible addition (new nullable field, new enum value).
- **PATCH** — documentation/metadata only.

`dpm breaking-changes` compares Avro schemas across a git diff and `dpm suggest-version`
/ `check_version_bump` verify that the version bump matches the detected change. A
breaking change without a MAJOR bump fails CI.

### A breaking change is a lifecycle, not an in-place edit

A MAJOR bump does not mean mutating the live contract in place. A breaking change is
published as a **new version that runs side by side** with the current one (the manifest's
`deprecation.successor` points to it). The previous version stays `active` through a
migration/grace period — its length is **agreed per contract** (there is no fixed minimum)
and recorded in the `deprecation` section (`sunset_date`) — then moves `deprecated` →
`retired`. `manifest_version` records the new major.

**Who has to migrate, and the deadline.** The migration window is the **data owner's** call —
the publisher sets how long a deprecated version is supported; `sunset_date` is when that
support ends. The contract declares the known, **critical** consumers (`lineage.downstream`,
and `deprecation.remaining_consumers` while sunsetting); the full population is tracked
**outside DPM**, in your access/policy layer (for example OPA — DPM does not mandate a specific
engine).

Criticality decides what gates the timeline. **Critical consumers gate it:** if one cannot
migrate by `sunset_date`, the steward negotiates an extension with the publisher rather than
cutting it off. **Non-critical consumers do not gate it:** once `sunset_date` (plus any agreed
extensions) passes, the old version is retired even if some of them have not migrated.

DPM checks the version bump and schema compatibility. Publishing both versions, resolving the
consumer set and running the migration are operational responsibilities of the producer and
the steward — see the steward guide for the procedure.

## Exceptions (waivers)

If a rule must be bypassed for a specific change, the owning team and the product's
`CODEOWNERS` agree on a waiver in the merge request description, stating the rule, the
reason and an expiry. Waivers are visible in Git history and revisited at expiry. There
is no silent bypass — the rule stays enforced for everyone else.
