# ResuLex

Turns plain resume text into structured JSON: contact details, work history, education, licenses,
certifications, skills, languages, specialties and availability. It uses rules, reference vocabularies
(O*NET, ESCO, CareerOneStop, NUCC) and the small spaCy English model. No LLM, no network at parse time,
and a typical resume parses in tens of milliseconds.

The name is resume + lexicon: every value is found by matching text against a vocabulary of job titles,
credentials and skills. That matching works on any text, such as a job description; the structural fields
(name, experience, education) expect a resume.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                        # installs spaCy, en_core_web_sm and openpyxl
uv run python cli.py build     # compiles vocab/ into index.pkl
```

`index.pkl` is not committed. Rebuild it whenever `config.toml` or anything under `vocab/` changes; the
parser refuses to run on an out-of-date index and tells you to rebuild.

## Usage

```sh
uv run python cli.py parse resume.txt              # print JSON to stdout
cat resume.txt | uv run python cli.py parse -      # read from stdin
uv run python cli.py parse resume.txt --today 2026-10-30
```

`--today` is the date used for "Present" when computing job durations (default: today). Pass a fixed
date to get reproducible output.

### Browser UI

```sh
uv run python ui/server.py              # http://127.0.0.1:8000
uv run python ui/server.py --port 9000
```

Paste text or drop a `.txt` file and press **Extract** (⌘/Ctrl + Enter). The page shows the extracted
fields next to the source text, with every value linked to the place in the text it came from. The server
listens on localhost only, since resumes are personal data.

### Output

The top-level fields are:

| Field | What it holds |
|---|---|
| `name`, `credentials`, `headline` | Name, post-nominal credentials ("RN, BSN") and headline lines from the top block |
| `email` / `emails`, `phone` / `phones`, `urls` | Contact details; `phones` items have `number` and `type` |
| `location` | `{city, state, zip}` |
| `job_title`, `industry` | From labeled profile exports ("Job Title: ...") |
| `summary`, `claimed_years` | Summary paragraph and any "10+ years" claim in it |
| `experience` | Jobs: `title`, `company`, `location`, `start`, `end`, `months`, `bullets` |
| `total_experience_months` | Sum of job intervals, overlaps counted once |
| `education` | `degree`, `level`, `field`, `school`, `location`, `year`, `gpa` |
| `occupation_group`, `occupations` | Inferred O*NET-SOC major group and up to three likely occupations |
| `licenses`, `certifications` | `name`, `acronym`, `issuer`, `state`, `status`, `year`, `kind`, `label`, `confidence` |
| `acronyms` | Acronym ↔ long form pairs found in the text |
| `languages` | `language` and `proficiency` |
| `skills`, `specialties` | `text`, `type`, `label`, `confidence`, highest confidence first |
| `availability` | `work_mode`, `shifts`, `employment_type` lists |
| `seniority` | Level of the latest job title or headline: intern, entry level, senior, lead, manager, director, ... |
| `other_sections` | Lines of sections the parser recognizes but does not interpret (projects, awards, ...) |

`label` is the canonical name from the vocabulary when a match was found; `confidence` is 0–1.

## Evaluating

```sh
uv run python cli.py eval eval/ --today 2026-10-30
```

For every `NAME.txt` in the folder, `eval` compares the parse with the expected answers in `NAME.json`
and prints what was missed or extra per resume, totals per field, and median/max parse time. Resumes
without a matching `.json` are skipped.

Real resumes are personal data: `eval/`, `resume.txt` and `*.resume.txt` are gitignored. Keep them out of
the repository.

## How it works

1. **Sections** — lines are split into sections by header words listed in `[sections]` of `config.toml`.
2. **Contact block** — name, email, phone, URLs and location come from the top of the resume.
3. **Experience and education** — entries are split on date ranges and parsed into fields; total
   experience is the union of the job intervals.
4. **Occupation profile** — job titles and credentials are matched to O*NET-SOC codes and weighted, which
   gives the resume an occupation group.
5. **Credentials and skills** — phrases are looked up in the index and scored by how they were found,
   which section they came from, how specific the phrase is and whether it fits the occupation group
   (so "EMR" in a nurse's resume is not read as the EMT credential).

The modules:

| File | Role |
|---|---|
| `cli.py` | Command line: `build`, `parse`, `eval` |
| `parse.py` | Resume text → fields |
| `match.py` | Tokenizer and normalization shared with the build, index lookup, confidence scoring |
| `build.py` | Compiles `vocab/` into `index.pkl` |
| `config.toml` | Section headers, scoring weights, stoplists, occupation groups |
| `tools/import_vocab.py` | Generates `vocab/imported/` from raw reference data |
| `ui/` | Browser UI: `server.py` serves the page and a `/api/parse` endpoint |

## Vocabulary

The index is built from JSON files in `vocab/`, one per entity type:

- `vocab/curated/` — hand-maintained lists. **Edit these.** For a given type, curated entries load before
  imported ones, so a curated label wins for a shared id.
- `vocab/imported/` — generated by `tools/import_vocab.py`. Do not edit by hand.

Each file looks like:

```json
{
  "type": "cert",
  "entities": [
    {
      "id": "family nurse practitioner board certified",
      "label": "Family Nurse Practitioner - Board Certified",
      "source": "curated_certifications",
      "aliases": ["ANCC FNP"],
      "cased": ["FNP-BC"],
      "socs": {"29-1171.00": 1.0}
    }
  ]
}
```

`aliases` match case-insensitively; `cased` aliases (acronyms) must match exactly. `socs` links the entity
to O*NET-SOC occupations with a weight. `removals.json` lists phrases to drop, per type.

After editing, run `uv run python cli.py build`.

### Regenerating imported vocabulary

Only needed when the raw reference data changes, such as a new O*NET release:

```sh
uv run python tools/import_vocab.py --raw ../data
```

The raw data is not in this repository. `tools/import.toml` maps each raw source (TSV, CSV, JSON, SQL
dumps, XLSX crosswalks) to entity types; paths in it are relative to `--raw`.

## Formatting

```sh
uvx ruff format .
```

## License

The code is under the [MIT License](LICENSE). The files in `vocab/imported/` are derived from third-party
reference data (O*NET, ESCO, CareerOneStop, NUCC, GeoNames and others), which keeps its own terms of use.
