# DPM — Data Product Manifest

**DPM** — open source toolkit for describing, validating and governing **data products as code**.

A Data Product Manifest (DPM) is a machine-readable definition of a data product: schema, SLA, quality rules, ownership, lineage, governance metadata and operational runbook — stored as versioned files in Git.

> Not another generic "data contracts" repo. DPM focuses on the full **data product** lifecycle, not just schema.

## Quickstart

```bash
git clone https://github.com/open-dpm/dpm.git
cd dpm
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Validate example manifest
dpm validate examples/aviation/flights/manifest.yaml

# Run tests
pytest
```

## What is in a manifest?

Each data product lives in `examples/{namespace}/{entity}/`:

```text
examples/aviation/flights/
├── manifest.yaml          # Main index: metadata, version, links
├── schema.avsc            # Avro schema
├── semantics.yml          # Business meaning, AI/RAG hints
├── quality_rules.yml      # Executable quality rules
├── sla.yml                # Freshness, availability, retention
├── physical_layout.yml    # Storage layout
├── runbook.md             # Operations guide
└── CODEOWNERS             # Review ownership
```

## CLI

| Command | Description |
|---------|-------------|
| `dpm validate` | Validate manifest structure and references |
| `dpm validate-rules` | Validate quality_rules.yml |
| `dpm governance` | Check governance requirements (owner, SLA, PII) |
| `dpm breaking-changes` | Detect breaking schema changes in git diff |
| `dpm suggest-version` | Suggest semver bump |

The rules these commands enforce are documented in [docs/DATA_GOVERNANCE_SPEC.md](docs/DATA_GOVERNANCE_SPEC.md).

## CI integration

- **GitLab CI** (recommended for corporate/self-hosted): see [docs/ci-gitlab.md](docs/ci-gitlab.md)
- **GitHub Actions** (public repo): see [docs/ci-github.md](docs/ci-github.md)

Copy `ci/gitlab/dpm-manifests.yml` into your manifests repository or include it from this repo.

## Guides

- [docs/gitlab-setup.md](docs/gitlab-setup.md) — mirror DPM into your own GitLab and pull updates
- [docs/steward-guide.md](docs/steward-guide.md) — set up a business-domain manifest repository

## Create a new manifest

```bash
cp -r templates/ examples/my_domain/my_product/
# Edit manifest.yaml from manifest-template.yaml
dpm validate examples/my_domain/my_product/manifest.yaml
```

## DPM vs data contracts (ODCS)

A "data contract" — as captured by the [Open Data Contract Standard (ODCS)](https://github.com/bitol-io/open-data-contract-standard) — is the interface between a data producer and its consumers: schema, SLA and quality expectations. DPM is a **superset** aimed at the full data product: it keeps the contract but adds business semantics (for AI/RAG), physical layout, an operational runbook, lineage, lifecycle/versioning and governance enforced in CI.

| Concept | ODCS | DPM |
|---------|------|-----|
| Schema | `schema` | `schema.avsc` (Avro) |
| Quality expectations | `quality` | `quality_rules.yml` |
| SLA | `slaProperties` | `sla.yml` |
| Ownership | `team` / roles | `metadata.owner` + `CODEOWNERS` |
| Versioning | `version` | `manifest_version` (SemVer) + breaking-change detection |
| Business semantics | — | `semantics.yml` |
| Physical layout | — | `physical_layout.yml` |
| Operational runbook | — | `runbook.md` |

DPM uses its own multi-file Avro + YAML format and is **not** ODCS-compatible today. ODCS import/export is on the roadmap so DPM manifests can interoperate with the wider data-contract ecosystem.

## License

DPM is dual-licensed:

- **GNU AGPL-3.0-or-later** for open-source use — see [LICENSE](LICENSE). You may use, modify
  and run it freely, including commercially, as long as you honour the AGPL (publish the source
  of modified versions, including when offered over a network).
- A **commercial license** for organizations that cannot accept the AGPL terms (e.g. embedding
  in a closed product or running a closed managed service) — see [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

Running the `dpm` CLI to validate your own manifests does not make your data a derivative work
and needs no commercial license.

Contributions are accepted under the [Contributor License Agreement](CLA.md).

## Roadmap

See [CHANGELOG.md](CHANGELOG.md). Phase 2: PyPI publish, GitLab CE demo, runtime validator, integrations.
