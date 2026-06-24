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

**Set up once** (a local working copy that acts as a bridge):
```bash
git clone https://github.com/open-dpm/dpm.git
cd dpm
git remote add gitlab https://gitlab.example.com/data/dpm.git
```
What this means: your local repo now has two remotes (named addresses) — `origin` = GitHub
(where you pull from), `gitlab` = your GitLab (where you push to). The names are arbitrary labels.

**Each time a new version is out:**
```bash
git fetch origin --tags --prune     # get the latest code and tags from GitHub
git push gitlab main --tags         # push them to your GitLab
```

That's it — `data/dpm` now has the new commits and tags.

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

## Cheat sheet

- First time: **Import by URL** → `data/dpm`.
- Update: `git fetch origin --tags` → `git push gitlab main --tags`.
- Versioning for domains: a GitLab Release from the tag + the `DPM_PKG` group variable.
