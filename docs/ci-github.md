# GitHub Actions

GitHub Actions is used for the public repository [open-dpm/dpm](https://github.com/open-dpm/dpm): PR checks, Community Profile, Dependabot.

Workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)

For your manifests repository:

```yaml
- run: pip install "dpm @ git+https://github.com/open-dpm/dpm.git@main"
- run: dpm validate --all
```
