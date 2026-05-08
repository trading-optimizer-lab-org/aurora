FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy the source tree and install the package in editable mode in a
# single step. The earlier two-stage layout had stage 1 silently fail
# (`|| true`) because `pyproject.toml` references a `README.md` that did
# not exist yet, leaving stage 2 to do all the work without any cache
# benefit. Collapsing to one install removes that hidden failure.
COPY . /app/
RUN pip install --upgrade pip && \
    pip install -e ".[ml,ga,monitoring]"

ENTRYPOINT ["forge"]
CMD ["--help"]
