# Getting Started

## Install

```bash
pip install -e ".[dev]"
```

## Validate a manifest

```bash
dpm validate examples/aviation/flights/manifest.yaml
dpm validate --all
dpm validate-rules --all
dpm governance --all
```

## Create new data product

1. Copy `templates/` to `examples/{namespace}/{entity}/`
2. Rename and fill `manifest-template.yaml` → `manifest.yaml`
3. Set `manifest_version` (SemVer)
4. Run `dpm validate` before commit
