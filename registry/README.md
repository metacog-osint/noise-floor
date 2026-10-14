# Source registry

`sources.csv` lists every data source this project uses, considered, or rejected. A source must be in this file, with its licence recorded, before it can feed any layer. `tools/check_registry.py` enforces the rules in the pre-commit hook and in CI.

The registry merges two research passes:

- `docs/research/2026-10-06-sources.md` (tag `tracker-2026-10-06`)
- the Interference Watch planning guide of 13 Oct 2026 (tag `iw-guide-2026-10-13`). Its licence verdicts were **not** independently checked unless another tag says so.

The live checks of 14 Oct 2026 are tagged `live-2026-10-14`.

## Columns

| Column | Meaning |
|---|---|
| `id` | Stable identifier, used in code and in `raw_items` |
| `lane` | gnss-observed · maritime · declared · context · satcom · lf-hf · emitters · community · attribution |
| `licence` | The licence or terms as found. UNVERIFIED marks anything not read at the source |
| `commercial` | yes · no · ask (permission needed) · unverified |
| `use` | What the project may do with it (below) |
| `phase` | Merged-plan phase (DESIGN.md) where it first lands |
| `assessed` | Which pass assessed it, plus `live-YYYY-MM-DD` if fetched |

## Use values

| `use` | Meaning |
|---|---|
| `ingest` | Licence allows commercial use. May feed public layers. |
| `ingest-after-ok` | Needs permission or a terms check first. Not ingested until this row changes. |
| `private-watch` | Reuse terms unverified. Alerts and triage in the private watch only, never in a public layer. |
| `cite-only` | Facts are extracted with a citation and link. Text is never republished. |
| `visual-only` | An analyst looks at it, for example for validation side-by-sides. Never ingested. |
| `later` | Not yet assessed closely enough. Its phase is in the future. |
| `exclude` | Not used. |

## Rules (checked)

- `use=ingest` requires `commercial=yes`.
- `commercial=no` allows only `visual-only` or `exclude`.
- Every row needs a licence statement and an assessment tag.
- `ingest`, `ingest-after-ok` and `private-watch` rows need a phase.
