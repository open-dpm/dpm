# GitLab CI

GitLab CI is the primary scenario for corporate and self-hosted installations.

## In the DPM repository

The pipeline in [`.gitlab-ci.yml`](../.gitlab-ci.yml) runs:

1. `pytest` — unit tests
2. `dpm validate --all` — manifest structure
3. `dpm validate-rules --all` — quality rules
4. `dpm governance --all` — governance
5. `dpm breaking-changes` — breaking changes in the MR
6. `dpm suggest-version` — semver suggestion

## In your manifests repository

Copy or include [`ci/gitlab/dpm-manifests.yml`](../ci/gitlab/dpm-manifests.yml):

```yaml
include:
  - remote: 'https://raw.githubusercontent.com/open-dpm/dpm/main/ci/gitlab/dpm-manifests.yml'
```

Local install without PyPI:

```yaml
before_script:
  - pip install --quiet "dpm @ git+https://github.com/open-dpm/dpm.git@main"
  - dpm validate --all
```
