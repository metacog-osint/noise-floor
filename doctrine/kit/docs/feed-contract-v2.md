# Feed contract v2 (`tic-feed/2`)

Every program publishes its items in this shape: GeoJSON first (a FeatureCollection whose features carry these fields
in `properties`, with `geometry: null` for items with no place), or JSON lines of flat items. The machine-readable form
is [`schema/feed-item-v2.schema.json`](../schema/feed-item-v2.schema.json); the tradecraft linter
(`python tic.py lint`) checks everything below, including the conditional rules. A worked example is
[`tests/fixtures/good.geojson`](../tests/fixtures/good.geojson).

## Feed header (FeatureCollection)

`contract`, `program`, `generated_at`, `licence`, `attribution`, and `language_key` (a link to the
[language key](language-key.md)).

## Every item

| Field | Meaning | Basis |
|---|---|---|
| `contract`, `id`, `program`, `title` | `tic-feed/2`; stable id; program; what happened, one line | |
| `kind` | observation, assessment or forecast | ICD 203 standard 3 |
| `tier` | routine or anomaly (measured), warning (judged) | Grabo; NATO indicators versus indications |
| `status`, `msg_type`, `supersedes`, `valid_until` | actual/exercise/test/draft; new/update/cancel/error; the item replaced; expiry | CAP 1.2 |
| `human_review` | none, sampled or full | ICD 505 labelling idea |
| `us_person_data` | always `none`, asserted and checked | suite rule |
| `status_class` | assessed, reported or claimed (claims draw hollow and move nothing alone) | Watchfloor two-source rule |
| `data_as_of`, `published_at` | when it was true; when we published it (UTC, ending in Z) | ICD 206 |
| `countries` | ISO 3166-1 alpha-2 codes, `[]` for none | |
| `coverage_fraction` | share of expected observations received | Primer quality-of-information check |
| `method_version` | the method that made the item | |
| `sources[]` | `id`, `publisher`, `author`, `title`, `outlet`, `source_type`, `url`, `published_at`, `accessed_at`, `licence`, `descriptor` (credibility, reliability, provenance, collector or tool), `grade` (Admiralty, e.g. B2), `lineage_id`, `independence_group` | ICS 206-01 (2 Dec 2024) citation fields, without classification fields; Admiralty system |
| `geometry` or `visual` | a place on the map, or `{type, url}` for a graphic | ICD 203 standard 9; visual-first rule |

Optional on every item: `summary`, `evidence_hash` (`sha256:...`), `archive_url`, `requirement_ids[]`,
`precision_class`, `product_category`, and the tags below.

## Conditional fields

| When | Required | Basis |
|---|---|---|
| `tier` anomaly | `baseline_ref` {id, window, type fixed/rolling/both, version} | JP 2-01.3 conditioning warning |
| a judgment (`tier` warning, or `kind` assessment or forecast) | `summary`; `probability` with matching `likelihood_term`; `confidence` and `confidence_basis`; `alternatives[]` each with `hypothesis` and `tell_apart`; `change_from_prior` (and `change_reason` if it changed); `requirement_ids` or `warning_problem_id` | ICD 203 standards 2, 4, 5, 6, 7 |
| `kind` forecast | `resolution` {rule, source, resolve_by} and `valid_until` | Verdict pre-registration |
| `indicator_id` set | `hypothesis_id`, `direction` (supports/refutes/neutral), `indicator_state` (present/absent/no_data) | CIA Tradecraft Primer |
| `msg_type` update, cancel or error | `supersedes` | CAP 1.2 references |

Keep the raw copy of any dynamic web source for at least a year (ICS 206-01 and ICD 206); `evidence_hash` and
`archive_url` point to it.

## Tags

| Tag | Values | Source |
|---|---|---|
| `ie_aspect[]` | informational, physical, human (old "cognitive" maps to human) | Joint Concept for Operating in the Information Environment (2018); SOIE glossary quoting JP 3-04 |
| `pmesii_pt[]`, `ascope[]`, `continuum` | operational variables; civil considerations; cooperation/competition/armed conflict | FM 3-0; JP 3-57; JCC |
| `ncf[]` and derived `sector[]` | CISA's 55 National Critical Functions; the 16 sectors follow from the kit's published crosswalk | CISA NCF Set (2019) |
| `lifeline[]` | `{id, status}` for FEMA's eight lifelines; status unknown/significant/moderate/minimal/baseline | FEMA Toolkit 2.1 |
| `response_stage` | `ladder:value`, e.g. `pager:orange`, `easa_czib:active`, `state_travel_advisory:level_4` | each ladder's owner |
| `disarm_technique[]` | DISARM technique ids (influence operations only) | DISARM |

All vocabularies live in [`vocab/`](../vocab). Change them there, rebuild (`python tools/build_js.py`,
`python tools/build_schema.py`), run the tests, then sync to each program.
