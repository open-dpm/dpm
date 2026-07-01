# Mirror DPM into your GitLab

How to bring the DPM project from GitHub into your own GitLab once, and how to pull future
versions later. Done once by the owner/administrator of the target group.

Replace `gitlab.example.com` with your GitLab host and the `data` group with your own.

---

## Part 1. First import (via the GitLab UI, ~2 minutes)

1. In GitLab: **New project → Import project → Repository by URL**.
2. Fill in:
   - **Git repository URL:** `https://github.com/open-dpm/dpm.git`
   - **Project slug:** `dpm`
   - **Project URL (namespace):** `data`
   - Visibility: Internal (or Private).
3. Click **Create project**.

GitLab copies the whole repository, branches and tags. It is now available at
`gitlab.example.com/data/dpm` — your internal DPM that domain repositories will rely on.

> Import-by-URL copies the repository **once**. Automatic updates are a GitLab Premium feature
> (pull mirroring), so on the free tier new versions are pulled manually — see Part 2.

---

## Part 2. Pull new versions from GitHub

When a new DPM release appears on GitHub (e.g. `v0.3.0`), bring it into GitLab. Run this from
any machine with `git` installed.

**Set up once** — clone *your* GitLab repo and add GitHub as the upstream source:
```bash
git clone https://gitlab.example.com/data/dpm.git
cd dpm
git remote add upstream https://github.com/open-dpm/dpm.git
```
What this means: your local repo now has two remotes (named addresses) — `origin` = your GitLab
(where you push to, because you cloned it), `upstream` = GitHub (where you pull from). The names
are arbitrary labels.

**Each time a new version is out:**
```bash
git pull --ff-only upstream main --tags   # update local main from GitHub, and fetch its tags
git push origin main --tags               # push them to your GitLab
```

That's it — `data/dpm` now has the new commits and tags.

> Use `pull`, not `fetch`: `fetch` would update only the remote-tracking ref and leave your local
> `main` behind, so `push` would send nothing new. `--ff-only` keeps it a clean fast-forward — if
> someone accidentally committed to the mirror it fails loudly instead of making a merge mess (the
> mirror should only ever receive commits from upstream).

---

## Part 3. Cut a release inside GitLab (optional)

So domains can pin to a specific version, create a Release in GitLab:

1. `data/dpm` → **Deploy → Releases → New release**.
2. **Tag name:** pick an already-synced tag, e.g. `v0.3.0`.
3. Title = the same version; copy the notes from `CHANGELOG.md`.
4. **Create release**.

Domains can now reference `ref: v0.3.0` in their CI.

---

## Part 4. Let domains install the tool from your GitLab (once)

So domain repositories install DPM from your GitLab instead of GitHub, set a group-level
variable:

1. The `data` group → **Settings → CI/CD → Variables → Add variable**.
2. **Key:** `DPM_PKG`
3. **Value:** `dpm @ git+https://gitlab.example.com/data/dpm.git@v0.2.0`
   (use the current tag; update it when you move to a new version)
4. Flags:
   - **Mask variable** — leave **off**. Masking forbids whitespace, and this value contains
     spaces (`dpm @ git+...`); it is not a secret, so there is nothing to mask.
   - **Protect variable** — leave **off**. If protected, the variable is absent in
     merge-request and feature-branch pipelines (where validation runs) and `pip install` would
     get an empty value.
   - **Expand variable reference** — leave **unticked**; the value has no `$`, so it makes no
     difference either way.

   In short: **tick neither flag**, then Save.

> If you really want a maskable value, use the bare URL form without spaces —
> `git+https://gitlab.example.com/data/dpm.git@v0.2.0` — `pip install` accepts it just as well.

Every domain inside the `data` group that includes our CI template will now install the tool
from your GitLab automatically.

---

## Part 5. Faster CI with a prebuilt image (optional)

Installing DPM with `pip` on every pipeline is fine for a few repositories. With many domains and
frequent merge requests it adds up. A **prebuilt image** that already contains DPM removes the
install step entirely — the job just pulls the image and runs `dpm`.

Pick one of:

- **Public image (simplest).** Set a group-level variable `DPM_IMAGE = ghcr.io/open-dpm/dpm:0.1.0`
  (the GHCR tag has **no** `v` prefix).
- **Your own image (recommended inside the company).** The `build:image` job in the mirror's
  `.gitlab-ci.yml` builds the `Dockerfile` with kaniko and pushes it to your GitLab Container
  Registry as `registry.gitlab.example.com/data/dpm:<git-tag>` + `:latest`. Then set the group
  variable `DPM_IMAGE = registry.gitlab.example.com/data/dpm:v0.1.0` — the GitLab image tag is the
  **git tag itself**, i.e. **with** the `v` (kaniko uses `$CI_COMMIT_TAG`).

**How the build is triggered.** `build:image` runs only in a **tag pipeline** (`rules: if: $CI_COMMIT_TAG`):

- **A tag that came in via import** (e.g. `v0.1.0`) already exists and never ran a pipeline — and you
  cannot re-create it. Build it once **manually**: `data/dpm` → **Build → Pipelines → Run pipeline** →
  in *Run for*, pick the **tag** `v0.1.0` → **Run**. That tag pipeline sets `CI_COMMIT_TAG`, so
  `build:image` runs and pushes `…/dpm:v0.1.0` + `:latest`.
- **New versions** synced later (Part 2, `git push origin main --tags`) push a *new* tag, which
  triggers the tag pipeline **automatically** — the image builds with no manual step.

**No variables to fill in.** `CI_REGISTRY`, `CI_REGISTRY_IMAGE`, `CI_REGISTRY_USER` and
`CI_REGISTRY_PASSWORD` are **GitLab-predefined** — GitLab injects them per job; you do not set them.
You only need the project's **Container Registry enabled** (`data/dpm` → **Settings → General →
Visibility, project features, permissions → Container Registry** = on) and a registry configured on
the GitLab instance. If the instance has no registry, push to Harbor instead (see the note below).

Set `DPM_IMAGE` with the same flags as `DPM_PKG` — **Mask off, Protect off**. Domains need no
changes: the CI template uses the image when `DPM_IMAGE` is set and skips `pip install`.

> The image is built with **kaniko** — no Docker daemon and no privileged mode — so it runs on
> locked-down shared runners where docker-in-docker is forbidden.
>
> Two adjustments for restricted setups: if your runners cannot reach `gcr.io`, set
> `KANIKO_IMAGE` to a mirror of kaniko (in Harbor or your GitLab); if you push to **Harbor**
> instead of the GitLab registry, change the `--destination` in `build:image` and supply Harbor's
> credentials.

---

## Cheat sheet

- First time: **Import by URL** → `data/dpm`.
- Update: `git pull --ff-only upstream main --tags` → `git push origin main --tags`.
- Versioning for domains: a GitLab Release from the tag + the `DPM_PKG` group variable.
- Faster CI: build/pull a DPM image and set the `DPM_IMAGE` group variable (skips `pip install`).
  Own image: enable the Container Registry, then **Run pipeline** on the existing tag once (new
  synced tags build automatically); use the tag **with** the `v` for the GitLab image.
