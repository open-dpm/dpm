FROM python:3.12-slim

WORKDIR /app
COPY . /app

# Install the package and its runtime dependencies only.
RUN pip install --no-cache-dir .

# `dpm` is now on PATH. No ENTRYPOINT — CI jobs provide their own commands.
