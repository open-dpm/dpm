# Contributing to DPM

Thank you for your interest in the project. Contributions are welcome.

## Development setup

```bash
git clone https://github.com/open-dpm/dpm.git
cd dpm
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Workflow

1. Fork / branch from `main`
2. Conventional Commits (English): `feat(validators): add X`
3. Ensure `pytest` passes
4. Open PR with description and test plan

## Contributor License Agreement

DPM is dual-licensed (AGPL-3.0 and a separate commercial license), so every contributor must
agree to the [Contributor License Agreement](CLA.md) once. When you open your first pull
request, the CLA bot will ask you to sign by posting this comment on the PR:

> I have read the CLA Document and I hereby sign the CLA

The bot records your signature and won't ask again. PRs cannot be merged until the CLA is signed.

## Code style

- Python 3.11+
- Type hints where practical
- Public docs and user-facing messages in English
- Commit messages: Conventional Commits, English, single line
