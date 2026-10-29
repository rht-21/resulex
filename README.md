# ResuLex

Turns plain resume text into structured JSON: contact details, work history, education, licenses,
certifications, skills, languages, specialties and availability. It uses rules, reference vocabularies
(O*NET, ESCO, CareerOneStop, NUCC) and the small spaCy English model. No LLM, no network at parse time,
and a typical resume parses in tens of milliseconds.

The name is resume + lexicon: every value is found by matching text against a vocabulary of job titles,
credentials and skills. That matching works on any text, such as a job description; the structural fields
(name, experience, education) expect a resume.

## Install

Requires Python 3.12+.

```sh
pip install resulex
python -m spacy download en_core_web_sm   # the spaCy model is not on PyPI; install it once
```

The package ships with a prebuilt index, so parsing works straight away.

## Usage

### Python

```python
from datetime import date

import resulex

result = resulex.parse(text)                              # dict; see Output below
result = resulex.parse(text, today=date(2026, 10, 30))

parser = resulex.Parser()                                 # loads the index and spaCy once
results = [parser.parse(t) for t in texts]
```

`resulex.parse` creates a shared `Parser` on its first call (about a second), after which each resume
takes tens of milliseconds. A missing spaCy model raises `resulex.ModelNotInstalledError`, and an index
that does not match `config.toml` and `vocab/` raises `resulex.IndexOutOfDateError`; both messages say
what to run.

### Command line

```sh
resulex parse resume.txt                  # print JSON to stdout
cat resume.txt | resulex parse -          # read from stdin
resulex parse resume.txt --today 2026-10-30
```

`--today` is the date used for "Present" when computing job durations (default: today). Pass a fixed
date to get reproducible output. `python -m resulex` works the same as `resulex`.

### Browser UI

```sh
resulex serve                 # http://127.0.0.1:8000
resulex serve --port 9000
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
uv run resulex eval eval/ --today 2026-10-30
```

For every `NAME.txt` in the folder, `eval` compares the parse with the expected answers in `NAME.json`
and prints what was missed or extra per resume, totals per field, and median/max parse time. Resumes
without a matching `.json` are skipped.

Real resumes are personal data: `eval/`, `resume.txt` and `*.resume.txt` are gitignored. Keep them out of
the repository.

### How accuracy is calculated

No accuracy figures are published here: they depend on the labeled set in `eval/`, which stays private.
Run `eval` on your own set to get them.

For each field, `eval` turns the expected and the parsed value into a set of strings and compares the
sets. The strings are exact matches after this per-field normalization (from `EVAL_FIELDS` in `src/resulex/cli.py`):

| Field | Compared as |
|---|---|
| `name`, `email`, `phone`, `total_experience_months` | the value itself |
| `location` | `"City, ST ZIP"` |
| `occupation_group` | the SOC code, e.g. `29-0000` |
| `experience` | `"title @ company [start..end]"` per job; a job counts only if all four parts match |
| `education` | `"degree @ school"` |
| `licenses`, `certifications` | `name` |
| `specialties` | `text` |
| `skills` | `text`, lowercased |
| `languages` | `language` |
| `availability` | `"field:value"`, e.g. `work_mode:remote` |

Summed over all resumes, per field:

- **found** = |expected ∩ parsed|
- **missed** = |expected − parsed|
- **extra** = |parsed − expected|

`eval` prints these three counts. Precision, recall and F1 follow from them:

- **precision** = found / (found + extra): how much of what the parser returned is right
- **recall** = found / (found + missed): how much of what is in the resume the parser got
- **F1** = 2 · precision · recall / (precision + recall)

A field that is empty in the expected answers and empty in the parse adds nothing to any count.

### How confidence is calculated

`confidence` (0–1) on skills, specialties, licenses and certifications is a score, not a measured
probability. A match that links to a vocabulary entity scores (`score` in `match.py`):

```
confidence = min(1, base × specificity × section × (1 + coherence_boost × coherence))
```

| Term | Meaning | Values (`config.toml`) |
|---|---|---|
| `base` | How the phrase was found (`[match.base]`) | inline list item 0.95, skills-list item 0.9, phrase in running text 0.8, object of a bullet's verb 0.8 |
| `specificity` | How telling the phrase is, computed at build time | see below |
| `section` | Where it was found (`[match.section]`) | skills, certifications 1.0; summary, experience 0.85; top 0.8; education, other 0.6 |
| `coherence` | How strongly the entity is linked to the resume's likely occupations: the highest (occupation weight × O*NET link weight) over those occupations | 0–1 |
| `coherence_boost` | Weight of that link | 0.3 |

**Specificity** rewards longer and rarer phrases (`specificity` in `build.py`):

```
rarity      = 1 − ln(df) / ln(N)
specificity = min(1, 0.35 + 0.25 × (words − 1) + 0.45 × rarity)
```

`N` is the number of phrases in the index, and `df` is how many index phrases contain this phrase (as
itself or as a run of up to four words). A one-word phrase that appears nowhere else gets 0.35 + 0.45 = 0.8;
any two-word phrase that appears nowhere else reaches the cap of 1.

A skill that matches no vocabulary entity can still be kept if it was listed (a skills-list item or an
inline list). It scores `base × unlinked_spec × section`, where `unlinked_spec` is 0.6, 0.8 or 0.9 for
1, 2 or 3+ words. Outside the skills section, a phrase whose last word ends fewer than 5 known skills
(`head_support_min`) is multiplied by a further 0.6 (`unsupported_head_factor`).

Example: "Outbound prospecting and lead generation" in a skills list matches no entity, so it scores
0.9 (list item) × 0.9 (five words) × 1.0 (skills section) = **0.81**.

Results below `min_confidence` (0.45) are dropped. An entity tied only to other occupation groups than the
resume's is not linked at all; one tied to no occupation (such as CPR) always can be. An acronym that names several unrelated entities with no occupation link is also not
linked: "EMR" in a nurse's resume is not read as the EMT credential.

### What the browser UI's numbers mean

The UI's **text mapped** and **values located** figures measure how well the output lines up with the
text, not whether it is correct:

- **text mapped** = non-blank characters covered by some located value ÷ all non-blank characters
- **values located** = extracted values found verbatim in the text ÷ all extracted values (derived fields
  such as the occupation group are not counted)

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

The modules, in `src/resulex/`:

| File | Role |
|---|---|
| `__init__.py` | Library API: `parse`, `Parser` and the error types |
| `cli.py` | Command line: `build`, `parse`, `eval`, `serve` |
| `parse.py` | Resume text → fields |
| `match.py` | Tokenizer and normalization shared with the build, index lookup, confidence scoring |
| `build.py` | Compiles `vocab/` into `index.pkl` |
| `config.toml` | Section headers, scoring weights, stoplists, occupation groups |
| `ui/` | Browser UI: `server.py` serves the page and a `/api/parse` endpoint |

`tools/import_vocab.py`, outside the package, generates `vocab/imported/` from raw reference data.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync               # installs the package in editable mode, plus en_core_web_sm and openpyxl
uv run resulex build  # compiles src/resulex/vocab/ into src/resulex/index.pkl
```

`index.pkl` is not committed. Rebuild it whenever `config.toml` or anything under `vocab/` changes; the
parser refuses to run on an out-of-date index and tells you to rebuild.

## Vocabulary

The index is built from JSON files in `src/resulex/vocab/`, one per entity type:

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

After editing, run `uv run resulex build`.

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

## Releasing

The wheel includes `index.pkl`, so build the index before building the package:

```sh
uv run resulex build
uv build              # dist/resulex-<version>-py3-none-any.whl and .tar.gz
uv publish            # needs a PyPI token
```

Bump `version` in `pyproject.toml` for every release; PyPI never accepts the same version twice.

## License

The code is under the [MIT License](https://opensource.org/license/mit). The files in `src/resulex/vocab/imported/` are derived from third-party
reference data (O*NET, ESCO, CareerOneStop, NUCC, GeoNames and others), which keeps its own terms of use.
