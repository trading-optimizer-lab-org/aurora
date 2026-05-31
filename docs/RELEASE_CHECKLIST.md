# Aurora Release Checklist (R188)

This is the local-release checklist for Aurora. It assumes a single-operator
workflow where the wheel is built locally, installed into a clean venv, and
either kept on the operator's machine or distributed by hand. Public PyPI
publishing and Sigstore signing are documented as **optional** steps and only
become required if Aurora is distributed outside the operator's machine.

For the legacy rename context, see `CHANGELOG.md` and `core/env_compat.py`.

---

## 1. Pre-flight (mandatory)

Run these against a clean working tree, on the canonical interpreter
(`C:/Python314/python.exe` on the operator's machine).

1. **Full pytest fast suite**

   ```
   "C:/Python314/python.exe" -m pytest tests/ -m "not slow and not integration" \
       --ignore=tests/test_config.py --ignore=tests/test_property.py
   ```

   Baseline: 2828+ pass, 10 pre-existing fail (9 markov_switching statsmodels
   API drift + 1 lint_config AST scanner false positive). A release MUST NOT
   regress this baseline.

2. **Type check**

   ```
   "C:/Python314/python.exe" -m mypy .
   ```

   `pyproject.toml` already sets `check_untyped_defs = false` (gradual typing).
   New regressions in `warn_unused_ignores` / `warn_redundant_casts` block the
   release.

3. **Lint**

   ```
   "C:/Python314/python.exe" -m ruff check .
   ```

   The default lint gate is intentionally focused on correctness checks
   (`F821`, `F541`, `B008`, `B023`, `B904`). A clean run is mandatory. Broader
   style passes are not release blockers.

4. **Docs build (if Sphinx is set up)**

   ```
   "C:/Python314/python.exe" -m sphinx -b html docs docs/_build/html
   ```

   Skip if the project does not maintain a Sphinx tree. The repo currently
   uses Markdown docs only; this step is reserved for when an HTML site is
   wired up.

5. **Wheel build**

   ```
   "C:/Python314/python.exe" -m build
   ```

   Produces `dist/aurora-<version>-py3-none-any.whl` and a matching sdist.
   The version comes from `pyproject.toml::project.version`. Do not edit
   the version inside this checklist.

6. **Evidence pack**

   Capture the following artefacts under `dist/evidence/<version>/`:

   - Full `pytest` log
   - `mypy` report
   - `ruff` report
   - Wheel SHA-256: `python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" dist/aurora-<version>-py3-none-any.whl`
   - `git rev-parse HEAD`
   - `python --version`
   - `pip freeze` of the dev environment
   - Build timestamp (UTC, ISO 8601)

   These five fields make up the lightweight build provenance bundle:
   `commit + python_version + freeze + wheel_sha256 + build_timestamp`.

---

## 2. Wheel smoke (mandatory)

Verify the freshly built wheel installs and imports in a brand-new venv.

Automated path (recommended):

```
"C:/Python314/python.exe" tools/release_smoke.py
```

The script (`tools/release_smoke.py`) does:

1. `python -m build` to produce the wheel
2. `python -m venv` for a throwaway venv
3. `pip install <wheel>` into that venv
4. `python -c "import aurora; print(aurora.__version__)"`
5. `python -c "from aurora.cli.forge import main; main(['--version'])"`

It returns exit code 0 only when every step succeeds. The smoke script is a
manual tool, NOT a pytest fixture -- a wheel build is too slow to run on
every test run.

Manual sanity checks if the script is unavailable:

- `aurora --version` (or `forge --version` for the deprecated alias) prints
  `aurora <pyproject version>`.
- `aurora doctor` runs to completion and reports the expected provider /
  policy / snapshot status.
- `python -c "import aurora"` emits a single `DeprecationWarning`
  pointing at the v1.6 retirement target.

---

## 3. SBOM and vulnerability scan (optional)

These steps are NOT mandatory for a local-only release, but they are cheap
to run and worth including before any public distribution.

- **SBOM**

  ```
  "C:/Python314/python.exe" -m pip install --quiet cyclonedx-bom
  "C:/Python314/python.exe" -m cyclonedx_py environment -o dist/sbom.json
  ```

  No specific vendor is required. Any CycloneDX or SPDX generator is fine.

- **Vulnerability scan**

  ```
  "C:/Python314/python.exe" -m pip install --quiet pip-audit
  "C:/Python314/python.exe" -m pip_audit -r <(pip freeze)
  ```

  `pip-audit` is the recommended scanner because it reads the same
  Python ecosystem advisory feed (PyPA Advisory Database) that PyPI's
  Trusted Publishing pipeline uses. Treat findings as advisory; an
  unfixable transitive vuln does not block a local release but should
  be noted in the evidence pack.

---

## 4. Public signing and PyPI publishing (DEFERRED)

**Status: explicitly deferred until distribution is decided.**

Aurora is a solo-operator codebase. Until and unless the project publishes
public artefacts to PyPI (or any other registry), no public signing is
required.

When public distribution becomes a real plan, add these steps and **only
then** mark them mandatory:

- **PyPI Trusted Publishing**

  Configure a PyPI Trusted Publisher entry tied to a GitHub Actions
  workflow under `.github/workflows/release.yml`. This avoids long-lived
  PyPI tokens. See `https://docs.pypi.org/trusted-publishers/` for the
  current setup.

- **Sigstore / keyless signing**

  Use the GitHub OIDC -> Sigstore -> Rekor flow for keyless signing of
  the wheel + sdist. The signing artefacts live alongside the release
  in the GitHub release page and the Rekor transparency log. See
  `https://docs.sigstore.dev/python/` for the `sigstore-python`
  reference.

These remain **optional** and are intentionally not gated by this
checklist. Do not add them as required steps until the project actually
publishes.

---

## 5. Shim retirement (committed)

The Aurora rename (R23, v1.5.0) introduced two compatibility shims:

- The `aurora` import alias -- see `aurora/__init__.py`.
- The `QF_*` / `QFORGE_*` env var fallback -- see
  `core/env_compat.py::aurora_env`.

Both are scheduled for removal in **v1.6**. Cutover plan:

1. **Tag the last v1.5.x release** that ships the shim. Use a clear
   release-notes line such as: "Last release with `aurora` import
   alias and `QF_*` env vars; v1.6 removes them."
2. **Open a single retirement commit** on the v1.6 branch:
   - Delete the `aurora/` shim package directory.
   - Drop `"aurora"` from `pyproject.toml::tool.setuptools.packages`
     and `package-dir`.
   - Delete `core/env_compat.py` and replace any `aurora_env(...)` call
     site with a direct `os.environ[...]` read of the canonical `AU_*`
     name.
   - Update `CHANGELOG.md` with a `### Removed` entry.
   - Tag commit message: `feat: v1.6 -- retire aurora shim and QF_* env fallback`.
3. **Run the wheel smoke step (section 2) again** with the v1.6 wheel
   to confirm `import aurora` now raises `ModuleNotFoundError`.
4. **Update CLAUDE.md** to drop the legacy column from the runtime-paths
   env var table.

If a downstream consumer is still on the legacy names by the time v1.6
is cut, they get a hard import error. That is the contract the shim
window committed to in v1.5.0.

---

## 6. Quick reference

| Step | Mandatory | Tool |
| --- | --- | --- |
| Pytest fast suite | Yes | pytest |
| Mypy | Yes | mypy |
| Ruff | Yes | ruff |
| Sphinx docs | Optional (no HTML site yet) | sphinx |
| Wheel build | Yes | python -m build |
| Evidence pack | Yes | shell + git |
| Wheel smoke | Yes | tools/release_smoke.py |
| SBOM | Optional | cyclonedx-bom |
| Vuln scan | Optional | pip-audit |
| PyPI Trusted Publishing | Deferred | github actions + PyPI |
| Sigstore signing | Deferred | sigstore-python |
| Shim retirement (v1.6) | Yes (when cutting v1.6) | manual |
