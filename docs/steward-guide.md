# Data steward guide

Goal: set up a GitLab repository for a business domain (for example "warehouse"), keep the
manifests in separate directories, and connect our checks (CI/CD) from `data/dpm`. Follow the
steps top to bottom — that's all you need. Everything is done in the GitLab web UI.

Replace `gitlab.example.com` with your GitLab host and the `data` group with your own.

> You work alongside the domain's developers. The wiring below is simple and on you; the
> manifest content (schema, rules) is filled in together with the domain team.

---

## Step 1. Create the domain repository

1. **New project → Create blank project**.
2. **Project name:** the domain, e.g. `warehouse`.
3. **Namespace:** the **`data`** group.
4. Untick "Initialize repository with a README".
5. **Create project**.

You now have an empty `data/warehouse`.

---

## Step 2. Add a directory for the first manifest

Manifests live as `manifests/<entity>/` — one entity per directory. For warehouse stock, that's
`manifests/inventory/`.

Copy the template files from `data/dpm` (the `templates/` folder). For each file: open the
template in `data/dpm`, click **Open raw**, copy the text; then in your repo click **New file**,
paste it, and save under the right name (drop the `-template` suffix):

| From `data/dpm/templates/` | To your repo |
|---|---|
| `manifest-template.yaml` | `manifests/inventory/manifest.yaml` |
| `schema-template.avsc` | `manifests/inventory/schema.avsc` |
| `quality_rules-template.yml` | `manifests/inventory/quality_rules.yml` |
| `sla-template.yml` | `manifests/inventory/sla.yml` |
| `semantics-template.yml` | `manifests/inventory/semantics.yml` |

For more entities, just create more folders next to it: `manifests/shipments/`,
`manifests/suppliers/`, and so on.

---

## Step 3. Connect our checks (CI/CD)

In the repository root, create a file named **`.gitlab-ci.yml`** and paste exactly this:

```yaml
include:
  - project: 'data/dpm'
    ref: v0.2.0
    file: '/ci/gitlab/dpm-manifests.yml'

variables:
  DPM_MANIFESTS_PATH: "manifests"
```

That is all it takes for the repository to "inherit" our CI/CD: on every change GitLab runs the
DPM checks automatically. Nothing else to edit here.

- `ref: v0.2.0` pins the domain to a DPM version. Bump it only deliberately, when a new version
  is out and you are ready to move.

---

## Step 4. (Optional) Block merges with failing checks

`data/warehouse` → **Settings → Merge requests** → enable **"Pipelines must succeed"**. Then a
change cannot be merged while the checks are red. Recommended, not required.

---

## Step 5. How the work goes from here

1. Every manifest change is made on a **separate branch** and opened as a **Merge Request**.
2. GitLab runs the checks automatically. At the bottom of the MR: a **green check** = all good,
   a **red cross** = there are errors.
3. If red — open the failed job, read the message, match it against the cheat sheet below, fix.
4. If green — the change can be merged.

---

## Step 6. "Why is the check red" cheat sheet

| Message in the log | What it means | What to do |
|---|---|---|
| `Missing required metadata field: …` | a required field is empty | fill in `name` / `namespace` / `description` / `owner` |
| `owner_required` | no owner team or email | add `owner.team` and `owner.email` |
| `pii_flag` | no `pii` field, or it is not true/false | set `pii: true` or `pii: false` |
| `pii_conflict` | `pii: false`, but a schema field is marked `"pii": true` | make them agree: either `pii: true`, or remove the field flag |
| `Schema file not found` | the path to `schema.avsc` is wrong | check the file name/location |
| `version … does not match SemVer` | version is not like `1.0.0` | fix `manifest_version` |
| `Breaking changes require MAJOR version bump` | a breaking change (field removed/renamed/retyped) | bump MAJOR **and** follow the deprecation process — see Step 7 |
| `changelog …` | no changelog entry | add an entry to the manifest's `changelog` |
| `No manifests found` | manifests are not under `manifests/` | move them into `manifests/<entity>/` |

---

## Step 7. Manifest versions (in brief)

`manifest_version` is `MAJOR.MINOR.PATCH`:
- removed/renamed a field, changed a type → bump **MAJOR** (`2.1.0` → `3.0.0`);
- added an optional field → bump **MINOR** (`2.1.0` → `2.2.0`);
- fixed a description/rule/SLA → bump **PATCH** (`2.1.0` → `2.1.1`).
And add a short entry to the manifest's `changelog`.

**A MAJOR change is special — it is not just a bigger number.** A breaking change must not
break live consumers without warning. You publish the new version **side by side** with the
old one and run a managed migration before the old one is retired. The migration deadline
(`sunset_date`) is the **publisher's** decision, not yours. See Step 8 for how to run it.

---

## Step 8. Running a major-version migration

`sunset_date` is the day the old version stops being supported. It is set by the **data owner
(publisher)**, not by you — you carry it (and the rest of the `deprecation` section) into the
work, you don't invent it.

1. **Publish the new version side by side** with the old one. In the old contract set
   `status: deprecated`, `deprecation.successor` → the new version, and a `migration_guide`.
2. **Build the consumer list:** critical/known ones from the contract (`lineage.downstream`);
   the rest (the "long tail") from your access/policy layer (e.g. OPA) and/or from old-version
   usage metrics.
3. **Work consumers in priority order:** **critical first** (reach out personally, agree a plan
   and a date), then high/medium, then the non-critical tail (bulk notice + the deadline).
4. **Notify** each consumer: what changed, the `migration_guide`, the `sunset_date`.
5. **Track** progress in `deprecation.remaining_consumers` (status + target date), at least for
   the critical/known consumers.
6. **If a critical consumer cannot migrate by `sunset_date`** — this is the conflict you
   resolve: go to the publisher and agree to **extend** the support window. Do not cut off a
   critical consumer just to hit a date.
7. **At `sunset_date`** (including any agreed extensions): retire the old version —
   `status: retired`, stop the old pipeline — **even if some non-critical consumers have not
   migrated.** They were notified and given the window; non-critical consumers do not extend
   the deadline.

## If you get stuck

- A reference to copy from: `data/dpm` → `examples/aviation/flights/`.
- What is checked and why: `data/dpm` → `docs/DATA_GOVERNANCE_SPEC.md`.

## One-line summary

Create `data/<domain>` → add `manifests/<entity>/` from the templates → add `.gitlab-ci.yml`
(it pulls in our CI) → work through MRs; a green pipeline means it can be merged.
