# Literature Strategy Idea Discovery

Pipeline para construir un corpus reproducible de estudios y convertirlos en
ideas de estrategias para Aurora.

## Qué Hace

- Busca literatura con ESTUDIOS/OpenAlex.
- Pagina cada consulta con `per_page=200`.
- Ejecuta varias ordenaciones: relevancia, citas y fecha.
- Guarda todos los estudios encontrados, no solo los buenos.
- Deduplica por OpenAlex ID, DOI, título, título+año y título+primer autor.
- Descarga PDF legal si ESTUDIOS lo encuentra.
- Usa texto completo o abstract para extraer ideas.
- Clasifica cada idea como:
  - `ready_to_test`: Aurora tiene datos públicos suficientes;
  - `pending_data`: la idea es interesante, pero falta algún dato;
  - `not_strategy`: el estudio no produce una regla operable.

## Qué No Hace

- No ejecuta backtests.
- No abre locked.
- No usa validación.
- No inventa proxies para datos que faltan.

## Comando Local

```powershell
forge research literature-corpus-build `
  --run-id literature-nightly `
  --run-root outputs/literature `
  --per-page 200 `
  --pages-per-query 5 `
  --sorts relevance,citations,date `
  --max-studies-to-enrich 0 `
  --no-locked
```

`--max-studies-to-enrich 0` significa enriquecer todos los estudios
deduplicados que se encuentren.

## GitHub Actions

Workflow:

```text
.github/workflows/literature-strategy-idea-discovery-9h.yml
```

Antes de lanzarlo hay que configurar el repo de ESTUDIOS:

```text
ESTUDIOS_REPO_URL=https://github.com/<owner>/<repo-estudios>.git
```

Puede pasarse como input manual o como variable del repositorio.

## Artifacts

El artifact principal contiene:

- `literature_corpus.sqlite`
- `studies_all.csv`
- `studies_enriched.csv`
- `strategy_ideas_all.csv`
- `ideas_ready_to_test.csv`
- `ideas_pending_data.csv`
- `coverage_report.json`
- `failures_report.csv`
- `query_coverage.csv`

La tabla principal para revisar ideas accionables es:

```text
ideas_ready_to_test.csv
```
