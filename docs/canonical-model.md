# Canonical model conformance (Enterprise Data Model)

DPM lets a data product declare that it represents a shared business entity —
`Customer`, `Account`, `AircraftObservation` — and checks, in CI, that it
actually carries that entity's mandatory attributes. In DMBOK terms this is
conformance to the **Enterprise Data Model**: *"any project-level data model
must be based on the EDM."* It is **not** referential integrity (foreign keys
between rows); it is a design-time standard about an entity's structure and
meaning.

## The two artifacts

1. **Canonical entity** — the enterprise-level definition of a business
   concept. A definition *without rows*: not a dataset. It is itself a DPM
   contract (`manifest.yaml` + `schema.avsc`) marked `kind: canonical_entity`.
2. **Data product** — a normal product (one that *publishes rows of* the
   entity) that opts in with `metadata.conforms_to`.

A product that merely *references* an entity by id (e.g. an `orders` table with
a `customer_id` column) does **not** conform to `Customer` — its rows are
orders, not customers. Only products whose rows *are* the entity declare it.

## Defining a canonical entity

Entities live in a registry — typically a dedicated repository owned by the
data-architecture team. Keep each major version in its own directory so live
majors coexist during migration:

```
canonical/
  customer/
    CODEOWNERS              # entity owner; nearest-CODEOWNERS-wins (see codeowners.py)
    v1/  manifest.yaml schema.avsc   # status: deprecated, with a sunset_date
    v2/  manifest.yaml schema.avsc   # status: active
```

The entity's **mandatory attributes are the non-nullable fields** of its
`schema.avsc`. Nullable / defaulted fields are optional. See
`templates/canonical-entity-template/`.

## Declaring conformance

In the product manifest:

```yaml
metadata:
  conforms_to:
    - entity: "aircraft_observation@1"   # pin the MAJOR version only
      rename:
        observed_at: "received_at"       # canonical attribute -> physical field
```

- Attributes match **by name** by default; use `rename` only where the physical
  field name differs from the canonical attribute name.
- Pin the **major** (`name@1`). Minor additions to an entity are optional by
  construction, so they never break a conformer — no need to bump the pin.

Check it:

```bash
dpm validate-conformance --all --registry-path path/to/canonical
```

A missing mandatory attribute, an incompatible type, or a nullable field used
for a mandatory attribute fails the build (`conformance_missing_attribute`,
`conformance_type_mismatch`, `conformance_nullable_attribute`). A product with
no `conforms_to` is outside the EDM and is ignored.

## Evolving an entity

Standard SemVer:

- **MINOR** — add an *optional* attribute, or clarify a definition. Conformers
  are unaffected.
- **MAJOR** — add a *mandatory* attribute, remove/rename one, or tighten a type.
  This is breaking. Create a new `vN/` directory, mark the previous version
  `status: deprecated` with a `sunset_date`, and let conformers migrate within
  the window. At sunset, delete the old `vN-1/` directory — any product still
  pinned to it then fails to resolve and goes red.

The softness comes from the coexistence window, not from versioning tricks. (If
you want an even gentler rollout of a future-mandatory attribute, the
expand-and-contract pattern works: ship it optional first (minor), let products
adopt it, then promote it to mandatory in a later major.)

### Who still needs to migrate?

Before a major bump or a sunset, list the conformers so you can notify them:

```bash
dpm conformance-impact --entity aircraft_observation --version 1 --base-path .
```

This scans manifests for `conforms_to: aircraft_observation@1` and prints each
product with its owner contact.

> **Limitation.** The list is only as complete as the manifests visible under
> `--base-path`. In a multi-repo setup, products live in many domain repos, so
> run this against an aggregated checkout or a central catalog to be
> exhaustive. With a single repo it covers exactly that repo.

## CI wiring (GitLab)

The reusable template `ci/gitlab/dpm-manifests.yml` includes an optional
`dpm:conformance` job. Set, as group-level CI/CD variables:

- `DPM_CANONICAL_REPO_URL` — `host/path` of the canonical repo (no scheme). The
  job clones it read-only with `$CI_JOB_TOKEN`; add your group to the canonical
  repo's CI **job token allowlist** (Settings → CI/CD → Token Access), so no
  stored token is needed. Leave empty to skip the conformance job.

The canonical repo is pulled at its latest state and `conforms_to` pins the
major, so a sunset (removed `vN/`) turns laggards red automatically.
