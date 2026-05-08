# Docs Hosting Decision (R31)

## Status

Decision: **GitHub Pages**, branch-based, manual trigger initially.
Auto-publish on `main` once a stable canonical repo URL exists (R28
follow-up).

## Build

```bash
make docs PYTHON=path/to/python
# Output: docs/_build/html/
```

The Sphinx config under `docs/conf.py` ships with autodoc, autosummary,
napoleon, viewcode, intersphinx, sphinx-autodoc-typehints, myst-parser,
and the furo theme. Build is verified `-W` clean (warnings as errors)
in the verification snapshot dated 2026-05-08.

## Local viewing

```bash
make docs PYTHON=path/to/python
python -m http.server --directory docs/_build/html 8000
```

Then open `http://localhost:8000`.

## GitHub Pages

A future workflow `.github/workflows/docs.yml` will:

1. Run `make docs`.
2. Push the resulting `docs/_build/html/` tree to a `gh-pages` branch.
3. GitHub serves it at `https://<owner>.github.io/<repo>/`.

The workflow lands once R28 (canonical repo URL) closes. Until then,
operators run `make docs` locally.

## Read the Docs

Read the Docs is a viable alternative; a `.readthedocs.yaml` at the
repo root would auto-publish on every push. Reasons we picked GitHub
Pages over RTD:

- The docs build does NOT require any RTD-specific extras.
- GitHub Pages can serve the same artefacts produced by `make docs`,
  so local + production identical.
- Simpler permissions model.

If the project later wants RTD's PR-preview feature, the same Sphinx
config works there without modification; the `.readthedocs.yaml` adds
~10 lines.

## Internal mirror

For private deployments, the same `docs/_build/html/` tree drops into
any static host (Nginx, S3 + CloudFront, etc). No additional work
required.

## Out of scope

- API rate-card hosting: the API reference lives inside the docs.
- Versioned docs (per-release URLs): handled by GitHub Pages branch
  conventions; configure `gh-pages-vN` per release if needed later.
