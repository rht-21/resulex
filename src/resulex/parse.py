"""Turn resume text into a dict of fields."""

import re
from collections import defaultdict

from . import match
from .match import SKILL_ORDER

# \uf0xx: Word/PDF symbol-font bullets that come through as private-use characters.
BULLET = re.compile(r"^\s*(?:[•●▪◦‣∙·■□○◆❖➢►→✓✔*-]|[-–—o](?=\s)|\d{1,2}[.)](?=\s))\s*")
CREDENTIAL_WORD = re.compile(r"certif|licen|registered|board|life support|specialist|provider|registry|course", re.I)
# A short token with at least two capitals: "BLS", "CPhT", "PMHNP-BC" (not "CLINICAL", not "Spanish").
ACRONYM = re.compile(r"\b(?=[A-Za-z]*[A-Z][a-z]*[A-Z])[A-Za-z]{2,7}(?:-[A-Za-z]{1,5})?\b")
# In running text only explicit wording marks a credential; "Registered Respiratory Therapist" is a role.
MENTION_WORD = re.compile(r"certif|licen|life support|board[- ]certified", re.I)
MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
MONTHS = {
    m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)
}
YEAR = r"(?:19|20)\d{2}"
ONE_DATE = rf"(?:{MONTH}\.?,?\s+{YEAR}|\d{{1,2}}/(?:\d{{1,2}}/)?{YEAR}|{YEAR}|\d{{1,2}}/\d{{2}}(?!\d))"
PRESENT = r"(?:present|current(?:ly)?|now|today|ongoing|to date)"
DATE_RANGE = re.compile(rf"(?<![\d/])({ONE_DATE})\s*(?:-|–|—|to|until|through|thru)\s*({ONE_DATE}|{PRESENT})\b", re.I)
MONTH_DATE = re.compile(rf"\b(?:{MONTH}\.?,?\s+{YEAR}|\d{{1,2}}/{YEAR})\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(
    r"(?<![\d+])(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s./-]{0,2}\d{3}[\s.-]?\d{4}(?!\d)"
    r"|\+\d{1,3}[\s.-]?\d{6,12}(?!\d)"
)
URL = re.compile(r"(?:https?://|www\.)\S+|(?:linkedin\.com|github\.com)/\S+", re.I)
ORG = re.compile(
    r"\b(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co|Group|Hospital|Health|Healthcare|Medical|Center|Centre|"
    r"Clinic|University|College|School|Institute|Bank|Agency|Department|County|Services|Solutions|Systems|"
    r"Technologies|Labs|Laboratories|Foundation|Partners|Associates|Pharmacy|Consulting|Industries|"
    r"International|Holdings|Enterprises|Network|Association|Authority|Office)\b\.?"
)
# Unfilled resume-template text: "Name of Certificate/Degree/Certification", "Name of School".
TEMPLATE_PROMPT = re.compile(r"\bName of [A-Za-z]+(?:\s*/\s*[A-Za-z]+)*")
SCHOOL_WORDS = re.compile(r"\b(?:University|College|Institute|School|Academy|Polytechnic|Conservatory|Seminary)\b")
CAP_RUN = re.compile(r"(?:[A-Z][\w&.'’-]*|of|the|and|for|at|&)(?:\s+(?:[A-Z][\w&.'’-]*|of|the|and|for|at|&))*")
ISSUER = re.compile(
    r"\b(?:Board|Association|Council|Commission|Institute|Society|Academy|Department|Registry|Bureau|"
    r"Agency|Federation|Alliance|Red Cross)\b"
)
STATUS = re.compile(
    r"\b(active|current|valid|inactive|expired|lapsed|pending|in progress|eligible|multistate|"
    r"compact|by endorsement|expected)\b",
    re.I,
)
# Unfilled template text on a credential line: "[License #]", "— Include if obtained".
PLACEHOLDER = re.compile(
    r"\s*\[[^\]]*\]|\s*[-–—]\s*(?:include )?if (?:obtained|applicable|completed|available)\b.*", re.I
)
# "License #: RN-000000-WI", "License No. 12345", "Washington State License AP30004736": a credential number; a bare
# four-digit number is a year, not a number.
LICENSE_NUMBER = re.compile(
    r"\s*(?:(?:#|\bNo\.|\bNumber\b|\bNum\.)\s*:?\s*(?P<n>[A-Z0-9][A-Z0-9-]{2,})"
    r"|(?<![\w-])(?=[A-Z0-9-]*\d)(?P<n2>(?:[A-Z]{1,4}-?\d{4,}[A-Z0-9-]*|\d{5,}[A-Z0-9-]*|[A-Z]{1,4}-\d{3,}[A-Z0-9-]*))\b)"
)
EXPIRY = re.compile(r"[\s,(]*\b(?:exp(?:ires|iration|\.)?|valid (?:through|until|thru))\b[^)]*\)?\s*$", re.I)
# "Skills: Word, Excel": a label at the start of a line.
LABEL = re.compile(r"^[A-Z][\w &/+-]{1,30}:\s*")
# "P R O F E S S I O N A L   E X P E R I E N C E": a letter-spaced heading.
SPACED = re.compile(r"(?:[A-Z&]\s+)+[A-Z&]")
CLAIMED_YEARS = re.compile(r"\b(\d{1,2})\+?\s*(?:years|yrs)\b", re.I)
HANDLED_SECTIONS = {
    "top",
    "summary",
    "experience",
    "education",
    "certifications",
    "skills",
    "certifications_skills",
    "languages",
    "availability",
    "location",
    "mobile",
    "work_phone",
    "job_title",
    "industry",
}
OBJECT_PREPS = {"in", "on", "with", "using", "via", "through", "across"}
SKILL_LEAD = {
    "skilled",
    "experienced",
    "proficient",
    "expertise",
    "knowledge",
    "experience",
    "versed",
    "familiar",
    "trained",
    "certified",
    "specializing",
    "specialized",
}
STATES = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "District of Columbia": "DC",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
    "Puerto Rico": "PR",
}
STATE_NAME = re.compile(r"\b(" + "|".join(sorted(STATES, key=len, reverse=True)) + r")\b")
LOCATION = re.compile(
    r"([A-Z][A-Za-z.'’-]*(?:\s+[A-Z][A-Za-z.'’-]*){0,3}),\s*("
    + "|".join(STATES)
    + r"|[A-Z]{2})\b(?:,?\s+(\d{5})(?:-\d{4})?)?"
)

TRAILING_PLACE = re.compile(
    r",\s*([A-Z][A-Za-z.'’-]*(?:\s+[A-Z][A-Za-z.'’-]*){0,2}),\s*("
    + "|".join(STATES)
    + r"|"
    + "|".join(STATES.values())
    + r")\s*$"
)

_nlp = None


class ModelNotInstalledError(Exception):
    """The spaCy model en_core_web_sm is not installed."""


def nlp():
    global _nlp
    if _nlp is None:
        import spacy

        if not spacy.util.is_package("en_core_web_sm"):
            raise ModelNotInstalledError(
                "spaCy model en_core_web_sm is not installed; run: python -m spacy download en_core_web_sm"
            )
        _nlp = spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
    return _nlp


# ---------- text layout ----------


def split_sections(text, cfg):
    vocab = {match.norm(p): name for name, phrases in cfg["sections"].items() for p in phrases}
    words = {w for p in vocab for w in p.split()}
    sections = [("top", [])]
    for raw in text.splitlines():
        line = unspace(raw.strip())
        if not line:
            sections[-1][1].append("")  # kept so experience bullets can end at a blank line
            continue
        name, rest = header(line, vocab, words, sections[-1][0])
        if name:
            sections.append((name, []))
            if rest:
                sections[-1][1].append(rest)
        else:
            sections[-1][1].append(line)
    return sections


def unspace(line):
    """'P R O F E S S I O N A L   E X P E R I E N C E' -> 'PROFESSIONAL EXPERIENCE'; two or more spaces split words."""
    if not SPACED.fullmatch(line):
        return line
    return " ".join(re.sub(r"\s", "", w) for w in re.split(r"\s{2,}", line))


def header(line, vocab, words, current):
    """(section name, text after the header on the same line) when the line is a section header."""
    m = re.match(r"([A-Za-z][A-Za-z &/]{1,40}):\s*(.*)", line)
    if m and match.norm(m.group(1)) in vocab:
        name = vocab[match.norm(m.group(1))]
        if name == current and m.group(2):
            return None, None  # "Tools: Excel" inside a skills section labels a list, it does not start a section
        return name, m.group(2).strip()
    # "Work Experience From 04/2025 to 06/2026": a two-word header followed by content.
    m = re.match(r"([A-Z][a-z]+ [A-Z][a-z]+)\s+(\S.*)", line)
    if m and match.norm(m.group(1)) in vocab:
        return vocab[match.norm(m.group(1))], m.group(2).strip()
    if len(line) > 50 or line[-1] in ".,;":
        return None, None
    if not all(w[0].isupper() or w.lower() in ("and", "of", "the") for w in re.findall(r"[A-Za-z]+", line)):
        return None, None
    key = match.norm(line)
    if key in vocab:
        return vocab[key], ""
    toks = key.split()
    if 0 < len(toks) <= 5 and all(t in words or t == "and" for t in toks):
        if {"certifications", "skills"} <= {vocab[t] for t in toks if t in vocab}:
            return "certifications_skills", ""  # "CERTIFICATIONS & SKILLS": each item is one or the other
        # The head noun names the section: "Leadership Experience" is experience, "Summary of Experience" a summary.
        head = toks[toks.index("of") - 1] if "of" in toks[1:] else toks[-1]
        for t in [head] + toks:
            if t in vocab:
                return vocab[t], ""
    # "NURSING EXPERIENCE", "LICENSES/NATIONAL CERTIFICATIONS": an all-caps line ending in a section word.
    if 0 < len(toks) <= 5 and toks[-1] in vocab and line.upper() == line:
        return vocab[toks[-1]], ""
    # "Advanced Practice & Nursing Experience": in title case only "Experience" (a title can end in "Education").
    if 0 < len(toks) <= 5 and toks[-1] == "experience":
        return "experience", ""
    return None, None


def paragraphs(lines):
    """Join wrapped lines; a bullet, a 'Label:' line or a line after a full stop starts a new one."""
    out = []
    for line in lines:
        if not out or BULLET.match(line) or LABEL.match(line) or out[-1].endswith((".", ":")):
            out.append(BULLET.sub("", line))
        elif re.search(r"\w-$", out[-1]):
            out[-1] += line  # a word hyphenated across lines: "self-" / "direction"
        else:
            out[-1] += " " + line
    return out


def line_items(lines):
    """One item per line or bullet; only a line starting in lowercase continues the previous one."""
    out = []
    for line in lines:
        if out and not BULLET.match(line) and line[0].islower():
            out[-1] += " " + line
        else:
            out.append(BULLET.sub("", line))
    return out


def title_like(line):
    words = re.findall(r"[A-Za-z][\w'-]*", line)
    if 0 < len(words) <= 8 and sum(w[0].isupper() for w in words) >= 0.6 * len(words):
        return True
    # "Licensed Practical Nurse — Spa City Family Medicine Associates, Hot Springs, AR": a title and its employer.
    parts = re.split(r"\s[–—|·]\s|\s-\s", line, maxsplit=1)
    return len(parts) == 2 and len(words) <= 16 and not line.rstrip().endswith(".") and title_like(parts[0])


GLUED_MONTH = re.compile(rf"(?<=[a-z])(?=(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+{YEAR})")
DANGLING_DATE = re.compile(rf"(?:{ONE_DATE}\s*(?:-|–|—|to)|(?:-|–|—|to)\s*{MONTH}\.?)\s*$", re.I)
PAGE_HEADER = re.compile(r"\b(?:resume|résumé|curriculum vitae|page\s+\d+(?:\s+of\s+\d+)?)\b", re.I)


def tidy_experience(lines, name):
    """Rejoin a date range wrapped onto the next line ('November 2020-' / 'February 2026'); drop page headers."""
    out = []
    for line in lines:
        if (
            out
            and out[-1]
            and line
            and DANGLING_DATE.search(out[-1])
            and re.match(rf"(?:{ONE_DATE}|{PRESENT})\b", line, re.I)
        ):
            out[-1] = out[-1].rstrip() + " " + line
        elif (
            line
            and len(line.split()) <= 6
            and (PAGE_HEADER.search(line) or name and match.norm(line) == match.norm(name))
        ):
            continue  # "Janella Williams Resume", "Page 2 of 3"
        else:
            out.append(line)
    return out


DATE_FIRST = re.compile(rf"\s*{ONE_DATE}\s*(?:-|–|—|to)\s*(?:{ONE_DATE}|{PRESENT})\b", re.I)
DATE_ONLY = re.compile(rf"\s*{ONE_DATE}\s*(?:-|–|—|to|until|through|thru)\s*(?:{ONE_DATE}|{PRESENT})\s*", re.I)


def unzip_columns(lines):
    """A two-column export lists every role first and every date range after it; put each range under its role.

    'Hygienist / Green Dental / Hygienist / Highland Dental / Oct 2019 - Current / Aug 2016 - Apr 2022' becomes
    'Hygienist | Green Dental | Oct 2019 - Current' / 'Hygienist | Highland Dental | Aug 2016 - Apr 2022': one dated
    header line per role, which entry_blocks splits like any 'Title | Company | Dates' list.
    """
    out, i = [], 0
    while i < len(lines):
        if not (lines[i] and DATE_ONLY.fullmatch(lines[i])):
            out.append(lines[i])
            i += 1
            continue
        dates = []
        while i < len(lines) and (not lines[i] or DATE_ONLY.fullmatch(lines[i])):
            if lines[i]:
                dates.append(lines[i])
            i += 1
        # The header lines right before the dates: undated, unbulleted, title-like.
        k = len(out)
        while k and (
            not out[k - 1] or not BULLET.match(out[k - 1]) and not has_date(out[k - 1]) and title_like(out[k - 1])
        ):
            k -= 1
        heads = [l for l in out[k:] if l]
        group = len(heads) // len(dates) if len(dates) > 1 else 0
        if group in (1, 2, 3) and group * len(dates) == len(heads):
            out[k:] = [" | ".join(heads[n * group : (n + 1) * group] + [dates[n]]) for n in range(len(dates))] + [""]
        else:
            out += dates
    return out


def entry_blocks(lines):
    """Group experience lines into entries: header lines (title, company, dates) followed by bullets.

    `lines` keeps blank lines as "" so a blank line can end an unmarked bullet.
    """
    entries, after_blank = [], False
    lines = [l for i, l in enumerate(lines) if l or (i and lines[i - 1])]
    # Entries that open with their dates ("2006-2007 Lawnwood Medical Center – Ft. Pierce, FL" / "Nurse Tech"): only a
    # dated line starts the next entry, so a title line under the dates stays with them.
    date_led = bool(DATE_FIRST.match(next((l for l in lines if l), "")))
    for i, line in enumerate(lines):
        cur = entries[-1] if entries else None
        if not line:
            after_blank = True
            continue
        # "Pain Management Nurse Practitioner" / "• Advanced Pain Management | 2023 – 2025": a bulleted employer line.
        if (
            BULLET.match(line)
            and cur
            and not cur["bullets"]
            and not dated(cur)
            and DATE_RANGE.search(line)
            and len(line.split()) <= 12
        ):
            cur["head"].append(BULLET.sub("", line))
            continue
        if BULLET.match(line):
            if cur is None:
                cur = {"head": [], "bullets": []}
                entries.append(cur)
            cur["bullets"].append(BULLET.sub("", line))
        elif cur and cur["bullets"] and not after_blank and continues(cur["bullets"][-1], line):
            cur["bullets"][-1] += " " + line
        # A dated header-like line after bullets or after another dated header (two roles listed back to back).
        elif (
            cur
            and (cur["bullets"] or dated(cur))
            and has_date(line)
            and len(line.split()) <= 20
            and not line.endswith(".")
        ):
            entries.append({"head": [line], "bullets": []})
        elif cur and dated(cur) and not title_like(line):
            cur["bullets"].append(line)
        elif (
            cur is None
            or cur["bullets"]
            or (dated(cur) and (has_date(line) or not date_led and next_is_dated(lines, i)))
        ):
            entries.append({"head": [line], "bullets": []})
        else:
            cur["head"].append(line)
        after_blank = False
    return [e for e in entries if e["head"] or e["bullets"]]


def continues(prev, line):
    # A lowercase start, or a short tail ending a sentence the bullet left open ("Committee.").
    if line[0].islower() or line.endswith(".") and not prev.endswith((".", ";", ":", "!")):
        return True
    return not prev.endswith((".", ";", ":", "!")) and not DATE_RANGE.search(line) and not title_like(line)


def has_date(line):
    return bool(DATE_RANGE.search(line) or MONTH_DATE.search(line))


def dated(entry):
    return any(has_date(h) for h in entry["head"])


def next_is_dated(lines, i):
    nxt = next((l for l in lines[i + 1 :] if l), "")
    return not BULLET.match(nxt) and has_date(nxt)


def split_outside_parens(text, seps):
    parts, depth, cur = [], 0, ""
    for ch in text:
        depth += ch in "(["
        depth -= ch in ")]"
        if depth <= 0 and ch in seps:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip(" .\t") for p in parts if p.strip(" .\t")]


# ---------- dates and places ----------


def parse_date(s, is_end, today):
    s = s.lower().strip()
    if re.fullmatch(PRESENT, s):
        return today.year, today.month
    m = re.fullmatch(r"(\d{1,2})/(\d{2})", s)
    if m:  # "11/25": two-digit year, assumed to be within the last century
        yy = int(m.group(2))
        year = 2000 + yy if 2000 + yy <= today.year + 1 else 1900 + yy
        return year, min(max(int(m.group(1)), 1), 12)
    year = int(re.search(YEAR, s).group())
    m = re.match(MONTH, s)
    if m:
        return year, MONTHS[m.group()[:3]]
    m = re.match(r"(\d{1,2})/", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return year, int(m.group(1))
    return year, 12 if is_end else 1


def total_months(intervals):
    """Months covered by the intervals, counting overlaps once."""
    total, last_end = 0, None
    for start, end in sorted((s[0] * 12 + s[1], e[0] * 12 + e[1]) for s, e in intervals):
        if last_end is not None and start <= last_end:
            start = last_end + 1
        if end >= start:
            total += end - start + 1
        last_end = end if last_end is None else max(last_end, end)
    return total


def find_location(text, index):
    """First 'City, ST [ZIP]' that is a real US place, as (location, (start, end)) or (None, None)."""
    pos = 0
    while m := LOCATION.search(text, pos):
        # Matches can overlap ("Nursing, Kansas City, MO" first reads as "Nursing, Kansas"), so step one char.
        pos = m.start() + 1
        words, state, zipcode = m.group(1).split(), STATES.get(m.group(2), m.group(2)), m.group(3)
        for i in range(len(words)):
            city = " ".join(words[i:])
            if (city.lower(), state) in index["places"]:
                start = m.start(1) + len(" ".join(words[:i])) + (1 if i else 0)
                return {"city": city, "state": state, "zip": zipcode}, (start, m.end())
        if zipcode and index["zips"].get(zipcode, (None, None))[1] == state:
            return {"city": index["zips"][zipcode][0], "state": state, "zip": zipcode}, (m.start(), m.end())
    return None, None


def ym(d):
    return f"{d[0]:04d}-{d[1]:02d}"


# ---------- top of resume ----------


def contact_block(top, text, index):
    out = {
        "name": None,
        "display_name": None,
        "credentials": [],
        "headline": [],
        "email": None,
        "emails": [],
        "phone": None,
        "phones": [],
        "urls": [],
        "location": None,
    }
    out["emails"] = list(dict.fromkeys(EMAIL.findall(text)))
    out["email"] = out["emails"][0] if out["emails"] else None
    out["urls"] = sorted({u.rstrip(".,;)") for u in URL.findall(text)})
    # A name split over two lines ("FERDINAND" / "CIGARAL").
    if len(top) > 1 and all(re.fullmatch(r"[A-Z][A-Za-z'’-]+", l) for l in top[:2]):
        top = [top[0] + " " + top[1]] + top[2:]
    for line in top:
        loc, span = find_location(line, index)
        if loc and not out["location"]:
            out["location"] = loc
            line = line[: span[0]] + line[span[1] :]
        line = URL.sub("", PHONE.sub("", EMAIL.sub("", line)))
        line = re.sub(r"\b(?:phone|mobile|cell|tel|e-?mail)\s*:", "", line, flags=re.I)
        parts = [p.strip(" ,") for p in re.split(r"\s*[|•·∙-]\s*", line) if p.strip(" ,")]
        if not parts:
            continue
        if out["name"] is None:
            first, *rest = split_outside_parens(parts[0], ",") or [""]
            # PDF exports sometimes repeat the name: "Janella K. WilliamsJanella K. Williams".
            half = len(first) // 2
            if len(first) % 2 == 0 and first[:half] == first[half:]:
                first = first[:half]
            name, creds = split_credentials(first, index)
            # A title after the name on the same line: "Jordan Ellis controls engineer".
            lead, tail = NAME.match(name), ""
            if not name_like(name, index) and lead and lead.end() < len(name):
                name, tail = lead.group(), name[lead.end() :].strip()
            # "Ccu Rn at Baptist Health" is a headline: a role at an employer, not a name.
            if name_like(name, index) and not re.match(r"(?:at|@)\s", tail, re.I):
                out["name"] = name
                out["credentials"] = creds + [r for r in rest if re.fullmatch(r"[A-Z][A-Za-z-]{1,8}", r)]
                parts = ([tail] if tail else []) + parts[1:]
        out["headline"].extend(p for p in parts if not is_prose(p))
    if out["name"] is None:
        out["name"] = name_from_email(text, out["emails"], index)
        out["headline"] = [h for h in out["headline"] if h != out["name"]]
    out["display_name"] = display_name(out["name"])
    return out


def display_name(name):
    """'MARY D’ANGELO' -> 'Mary D’Angelo', 'sean mcdonald' -> 'Sean McDonald'; a mixed-case name is kept as written."""
    if not name or not (name.isupper() or name.islower()):
        return name

    def word(w):
        w = re.sub(r"[A-Za-z]+", lambda m: m.group().capitalize(), w.lower())  # also after ’ ' - .
        return re.sub(r"^Mc([a-z])", lambda m: "Mc" + m.group(1).upper(), w)

    return " ".join(word(w) for w in name.split())


# Lowercase surname particles are part of a name: "Jordan van Ellis", "Maria de la Cruz".
NAME = re.compile(
    r"[A-Z][A-Za-z.'’-]*(?:\s+(?:(?:van|von|de|da|del|der|di|du|la|le|dos|das|bin|al)\s+){0,2}[A-Z][A-Za-z.'’-]*){1,4}"
)


def is_prose(line):
    """A sentence-like line: many words, mostly lowercase, and no contact details (an address line is not prose)."""
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", URL.sub("", PHONE.sub("", EMAIL.sub("", line))))
    if len(words) < 10:
        return False
    return sum(w[0].islower() for w in words) >= 0.4 * len(words)


# Credential acronyms LinkedIn headlines write in title case ("Ccu Rn"); two-letter ones are kept to these, since
# "Ma" and "Do" are surnames.
TITLE_CASED_ACRONYMS = {"rn", "np"}


def name_like(s, index):
    """Two to five capitalized words that are not a job title, role headline, place, school or organization."""
    if not NAME.fullmatch(s or "") or SCHOOL_WORDS.search(s) or ORG.search(s):
        return False
    hits = match.find(s, index, {"title", "license", "cert", "specialty"})
    # One-word titles are common first names (Mason, Hunter, Dean); only a multi-word phrase rules a line out,
    # or a title next to a practice area ("Hospice Nurse").
    if any(h["words"] > 1 for h in hits):
        return False
    if any(h["type"] == "title" for h in hits) and any(h["type"] == "specialty" for h in hits):
        return False
    words = s.split()
    if any(credential_acronym(w, index) for w in words):
        return False  # "Consultant BCBA", "Orthopedic Surgery Pa-C", "Emergency Room Rn"
    return not is_place(words, index)  # "Lewisville Texas"


def credential_acronym(word, index):
    """'BCBA', 'Pa-C', 'Rn': a license, certification or degree acronym, in any case."""
    key = match.norm(word)
    if key in TITLE_CASED_ACRONYMS:
        return True
    letters = re.sub(r"[^A-Za-z]", "", word)
    entry = index["phrases"].get(key)
    if len(letters) < 3 or not entry:
        return False
    upper = match.case_key(t for t, _, _ in match.tokens(word.upper()))
    return any(c == upper and index["ents"][e][0] in ("license", "cert", "degree") for e, c in entry[1])


def is_place(words, index):
    """'Lewisville Texas', 'Austin TX': a city followed by its state."""
    for n in (2, 1):
        if len(words) > n:
            state = STATES.get(" ".join(words[-n:]), " ".join(words[-n:]) if n == 1 else None)
            if state and (" ".join(words[:-n]).lower(), state) in index["places"]:
                return True
    return False


def split_credentials(s, index):
    """'Debbie K. Mathew MSN' -> ('Debbie K. Mathew', ['MSN']): peel known credential acronyms off the end."""
    words, creds = s.split(), []
    while len(words) > 2:
        w = words[-1]
        entry = index["phrases"].get(match.norm(w))
        surface = match.case_key(t for t, _, _ in match.tokens(w))
        known = entry and any(
            c == surface and index["ents"][e][0] in ("degree", "license", "cert") for e, c in entry[1]
        )
        # An acronym not in the data ("MSPAS") after a mixed-case name; not the last word of "MARY ANN SMITH".
        unknown = (
            re.fullmatch(r"[A-Z]{2,6}(?:-[A-Z]{1,4})*", w)
            and ("-" in w or not words[-2].isupper())
            and not re.fullmatch(r"[IVX]+|JR|SR", w)
        )
        if not (known or unknown):
            break
        creds.insert(0, words.pop())
    return " ".join(words), creds


def name_from_email(text, emails, index):
    """A name-like line whose words all appear in an email address ('BAILEY SKAGGS' / bailey.skaggs@...)."""
    locals_ = [re.sub(r"[^a-z]", "", e.split("@")[0].lower()) for e in emails]
    for line in text.splitlines()[:60]:
        line = line.strip()
        # The email vouches for a lowercase name ("jordan ellis"), which name_like alone would not accept.
        lower = re.fullmatch(r"[a-z]+(?: [a-z]+){1,3}", line) and not any(
            h["words"] > 1 for h in match.find(line, index, {"title", "license"})
        )
        if (name_like(line, index) or lower) and any(
            all(w.lower().strip(".") in loc for w in line.split()) for loc in locals_
        ):
            return line
    return None


# ---------- experience ----------


def phones(sections):
    """Every distinct phone number, typed by the label above it ('Mobile', 'Work Phone') when there is one."""
    found = {}
    for name, lines in sections:
        kind = name if name in ("mobile", "work_phone") else None
        for line in lines:
            for m in PHONE.finditer(line):
                found.setdefault(m.group().strip(), kind)
    return [{"number": n, "type": k} for n, k in found.items()]


def segments(text, split_commas):
    commas = r"|,\s+(?![^()]*\))" if split_commas else ""
    # Tabs are column gaps in PDF exports: "Title\tCompany\tDates". A middle dot separates too.
    parts = re.split(r"\s*\|\s*|\s+[–—·]\s+|\s+@\s+|\s+at\s+(?=[A-Z])|\t+" + commas, text)
    # A spaced hyphen separates a title from its employer ("Technician - Bayou Recovery Center") but not an employer
    # from its unit ("Saint Rose Hospital - San Martin Campus"); an unspaced one is part of a word ("Medical-Surgical").
    parts = [q for p in parts for q in split_hyphen(p)]
    out = []
    for p in parts:
        p = p.strip(" \t,-–—|")
        if re.fullmatch(r"(?:Inc|LLC|Ltd|Corp|Co)\.?", p) and out:
            out[-1] += ", " + p
        elif p and re.search(r"[A-Za-z]", p):
            out.append(p)
    return out


ORG_END = re.compile(ORG.pattern + r"\s*$")


def split_hyphen(part):
    """'Technician - Bayou Recovery Center' -> 2 parts; 'Night Nurse - LPN or RN' and 'Hospital - Campus' stay one."""
    left, sep, right = part.partition(" - ")
    if not sep or ORG_END.search(left.strip()) or not ORG.search(right):
        return [part]
    return [left, *split_hyphen(right)]


def title_fit(seg, index):
    hits = match.find(seg, index, {"title", "license"})
    if not hits:
        return 0.0, []
    covered = sum(h["words"] for h in hits) / max(1, len(match.tokens(seg)))
    starts = match.norm(seg).startswith(match.norm(hits[0]["text"]))
    socs = sorted({s for h in hits for e in h["ents"] for s in index["socs"].get(e, ())})
    return covered + (0.5 if starts else 0.0), socs


def occupation_of(title, index):
    """The O*NET-SOC occupation a job title links to most strongly: {"code": "29-1141.00", "title": ...} or None."""
    hits = match.find(title or "", index, {"title", "license"})
    if not hits:
        return None
    best_soc, best_w = None, -1.0
    for e in max(hits, key=lambda h: h["words"])["ents"]:
        for soc in index["socs"].get(e, ()):
            w = index["rel"][soc].get(e, 0.0)
            if soc in index["soc_titles"] and w > best_w:
                best_soc, best_w = soc, w
    return {"code": best_soc, "title": index["soc_titles"][best_soc]} if best_soc else None


def ends_in_title(seg, index):
    hits = match.find(seg, index, {"title", "license"})
    return bool(hits) and match.norm(seg).endswith(match.norm(hits[-1]["text"]))


def parse_job(entry, index, today):
    # Lines joined by newlines so a date range wrapped onto the next line ("November 2020-\nFebruary 2026") matches.
    head = URL.sub("", PHONE.sub("", EMAIL.sub("", "\n".join(entry["head"]))))
    head = re.sub(r"\(\s*(?:remote|hybrid|on-?site)[^)]*\)", "", head, flags=re.I)
    head = GLUED_MONTH.sub(" ", head)  # "Chicago, IllinoisJanuary 2026": PDF text lost the column gap
    head = re.sub(r"\[[^\]]*\]", "", head)  # unfilled template text: "[Month Year] – Present"
    start = end = None
    m = DATE_RANGE.search(head)
    if m:
        start, end = parse_date(m.group(1), False, today), parse_date(m.group(2), True, today)
        present = bool(re.fullmatch(PRESENT, m.group(2).strip(), re.I))
        head = head[: m.start()] + head[m.end() :]
    elif m := MONTH_DATE.search(head):  # a single month: the job started and ended then
        start = end = parse_date(m.group(), False, today)
        present = False
        head = head[: m.start()] + head[m.end() :]
    head = re.sub(r"\(\s*\)", "", head)  # "Technician - Bayou Recovery (2022-2026)" leaves "()"
    loc, span = find_location(head, index)
    if loc:
        head = head[: span[0]] + head[span[1] :]
    # Title and company on their own lines: a comma is part of the title ("owner, physical therapist").
    line_of, segs, head_lines = [], [], head.split("\n")
    for li, line in enumerate(head_lines):
        for seg in segments(line, split_commas=len(entry["head"]) == 1):
            line_of.append(li)
            segs.append(seg)
    fits = [title_fit(s, index) for s in segs]
    # "medical doctor associates" reads like a title but is an employer; titles usually come first.
    org = re.compile(ORG.pattern, re.I)
    rank = [f - (0.5 if org.search(s) else 0) + (0.2 if i == 0 else 0) for i, (s, (f, _)) in enumerate(zip(segs, fits))]
    title_i = max(range(len(segs)), key=lambda i: rank[i], default=None)
    # A weak fit falls back to the first segment, unless the first has no fit and this one ends in its title word:
    # "Hope Home Care — Pediatric Home Care LPN".
    if title_i is not None and fits[title_i][0] < 0.4 and not (fits[0][0] == 0 and ends_in_title(segs[title_i], index)):
        title_i = 0
        # "Northwind Global Solutions" / "SDE-II": the first line is only the employer, the title is on the next line.
        if ORG.search(segs[0]) and fits[0][0] == 0 and line_of.count(0) == 1:
            title_i = next((i for i in range(1, len(segs)) if line_of[i] != line_of[0] and not ORG.search(segs[i])), 0)
    rest = [i for i in range(len(segs)) if i != title_i]
    # Company: an organization word, on another line than the title first ("Clinical Instructor – Medical-Surgical
    # Nursing" / "Chicago State University"), else the first segment on another line, else what is left.
    other_line = [i for i in rest if line_of[i] != line_of[title_i]] if title_i is not None else rest
    company_i = next((i for i in other_line + rest if ORG.search(segs[i])), (other_line or rest or [None])[0])
    company = re.sub(r"\s*\([^)]*\)", "", segs[company_i]).strip(" ,") if company_i is not None else None
    # "Spa City Family Medicine Associates, Hot Springs, AR": a "City, ST" tail the place data did not know.
    tail = TRAILING_PLACE.search(company or "")
    if tail and not loc:
        loc = {"city": tail.group(1), "state": STATES.get(tail.group(2), tail.group(2)), "zip": None}
        company = company[: tail.start()]
    title = segs[title_i] if title_i is not None else None
    if title_i is not None and company_i is not None and line_of[company_i] != line_of[title_i]:
        # The title line is all title: "Insurance Broker – Lead Qualification & Client Acquisition".
        title = head_lines[line_of[title_i]].strip(" \t,-–—|")
    return {
        "title": title,
        "company": company,
        "location": loc,
        "start": ym(start) if start else None,
        "end": ("present" if present else ym(end)) if end else None,
        "current": bool(end) and present,
        "months": total_months([(start, end)]) if start else None,
        "occupation": occupation_of(title, index),
        "socs": fits[title_i][1] if title_i is not None else [],
        "bullets": entry["bullets"],
        "_interval": (start, end) if start else None,
    }


# ---------- education ----------


def parse_education(lines, index):
    entries = []
    for line in lines:
        e = education_fields(BULLET.sub("", line), index)
        cur = entries[-1] if entries else None
        if cur is None or any(cur.get(k) and e.get(k) for k in ("degree", "school")):
            entries.append(e)
        else:
            cur.update({k: v for k, v in e.items() if v and not cur.get(k)})
    return entries


def education_fields(line, index):
    e = {"degree": None, "level": None, "field": None, "school": None, "location": None, "year": None, "gpa": None}
    line = TEMPLATE_PROMPT.sub("", line)
    loc, span = find_location(line, index)
    if loc:
        e["location"] = loc
        line = line[: span[0]] + line[span[1] :]
    m = DATE_RANGE.search(line)
    years = re.findall(YEAR, m.group() if m else line)
    e["year"] = int(years[-1]) if years else None
    m = re.search(r"\bGPA[:\s]*([0-4]\.\d{1,2})", line, re.I)
    e["gpa"] = float(m.group(1)) if m else None
    hits = match.find(line, index, {"degree"})
    if hits:
        h = hits[0]
        attrs = index["attrs"].get(h["ents"][0], {})
        e["degree"], e["level"], e["field"] = h["text"], int(attrs["level"]), attrs.get("field")
        pos = line.find(h["text"])
        before = re.split(r"[-–—,|(]", line[:pos])[-1].strip()
        after = re.match(
            r"\.?\s*(?:\([^)]*\))?\s*(?:,|in|of)?\s*([A-Z][A-Za-z&/ ]+?)(?=\s*(?:[-–—,|(]|\d|$))",
            line[pos + len(h["text"]) :],
        )
        if not e["field"] and after and not SCHOOL_WORDS.search(after.group(1)):
            e["field"] = after.group(1).strip()
        elif not e["field"] and before and before[0].isupper():
            e["field"] = before
    schools = [s.strip() for s in CAP_RUN.findall(line) if SCHOOL_WORDS.search(s)]
    if schools:
        e["school"] = re.sub(r"^(?:of|the|and|for|at|&)\s+|\s+(?:of|the|and|for|at|&)$", "", schools[0])
    elif e["degree"]:
        # "BSN, WNU, 2007": a school written as its acronym, the part that is not the degree, a state or a credential.
        e["school"] = next(
            (
                p
                for p in re.split(r"\s*[,|–—]\s*|\s+-\s+", line)
                if re.fullmatch(r"[A-Z]{2,6}", p)
                and p != e["degree"]
                and p not in STATES.values()
                and not credential_acronym(p, index)
            ),
            None,
        )
    return e


# ---------- licenses and certifications ----------


def looks_like_credential(item):
    """Filters out what spills into a certifications section: contacts, dates, sentences, stray symbols."""
    if EMAIL.search(item) or PHONE.search(item) or URL.search(item) or not re.search(r"[A-Za-z]{2}", item):
        return False
    if len(item.split()) > 15 or re.fullmatch(rf"[\W\d]*(?:{MONTH}\.?\s*)?[\W\d]*", item, re.I):
        return False
    if "•" in item or PAGE_HEADER.search(item) and len(item.split()) <= 6:
        return False  # a list of items joined onto one line; "JORDAN ELLIS | RESUME | 2"
    if re.match(r"(?:no|not)\s|(?:relevant\s+)?course(?:s|work)\b|(?:willing|able) to\s|must\s", item, re.I):
        return False  # "No OASIS certification", "Relevant coursework: ...", "Willing to complete the agility test"
    if re.search(r"reliable (?:vehicle|transportation)", item, re.I):
        return False  # a job requirement copied into the resume, not a credential held
    if re.search(r"continuing (?:medical |nursing )?education|\b(?:CME|CEU|CNE)s?\b.*credit", item, re.I):
        return False  # continuing-education hours are not a credential
    return not re.match(r"\d+(?:\.\d+)?\s+(?:clinical\s+)?hours\b", item, re.I)  # "250 hours of primary care"


def split_pair(part, index):
    """'ACLS & BLS' -> ['ACLS', 'BLS'] when every piece names a credential; otherwise [part]."""
    subs = re.split(r"\s*(?:&|\band\b)\s*", part)
    if len(subs) > 1 and all(match.find(s, index, {"license", "cert"}) for s in subs):
        return subs
    return [part]


def without_description(item):
    """'Certified Trainer: Certified to develop and lead training.' -> 'Certified Trainer'; 'AHA: BLS, ACLS' stays."""
    head, sep, tail = item.partition(": ")
    words = tail.split()
    if sep and len(words) >= 4 and sum(w[0].islower() for w in words) >= len(words) / 2:
        return head
    return item


def credential_items(lines, index):
    """Items of a credentials section; a line listing several ('BLS, ACLS, PALS') becomes one item each."""
    out = []
    for item in map(without_description, line_items(lines)):
        parts = [s for p in split_outside_parens(item, ",;|•") for s in split_pair(p, index)]
        # An issuer part ("National Board of Certification for ...") is not a credential of its own.
        named = [
            p
            for p in parts
            if match.find(p, index, {"license", "cert"}) and (ACRONYM.search(p) or not ISSUER.search(p))
        ]
        out.extend(named if len(named) > 1 else [item])
    return out


def parse_credential(item, index, cfg, soc_weights):
    if not looks_like_credential(item):
        return None
    statuses = [s.lower() for s in STATUS.findall(item)]  # before the placeholders go: "[in progress]"
    number = LICENSE_NUMBER.search(item)
    if number:
        item = (item[: number.start()] + item[number.end() :]).strip()
    years = re.findall(YEAR, item)
    item = PLACEHOLDER.sub("", re.sub(rf"\s*\((?:[^)]*\s)?{YEAR}\)", "", item)).strip(" -–—:")
    item = EXPIRY.sub("", item).strip(" -–—:,")  # "... license #135624    expires 9/30/2027"
    parts = split_outside_parens(item, ",")
    if not parts:
        return None
    name, *rest = parts
    acro = re.search(r"\(([A-Z][A-Za-z0-9&/-]{1,15})\)", name)
    issuer = next((r for r in rest if ISSUER.search(r)), None)
    hits = match.find(name, index, {"license", "cert"})
    org_hits = match.find(", ".join(rest), index, {"org"})
    if not issuer and org_hits:
        issuer = org_hits[0]["text"]
    state = STATE_NAME.search(item)
    # "Adult Gerontology NP Certified (AANP)" is a board certification even though "NP" names a license.
    # Not plain "board": a license's issuer is usually a State Board of Nursing.
    board_cert = re.search(r"certif|board[- ]certified|\b(?:ANCC|AANP|NCCPA|AACN)\b|-(?:BC|C)\b", item, re.I)
    licensed = "licen" in item.lower() or any(h["type"] == "license" for h in hits) and not board_cert
    kind = "license" if licensed else "cert"
    out = {
        "name": name,
        "acronym": acro.group(1) if acro else None,
        "issuer": issuer,
        "state": STATES[state.group(1)] if state else None,
        "status": statuses or None,
        "year": int(years[-1]) if years else None,
        "number": (number.group("n") or number.group("n2")) if number else None,
        "kind": kind,
        "id": None,
        "label": None,
        "source": None,
        "confidence": None,
    }
    hits = [h for h in hits if h["type"] == kind] or hits
    if hits:
        best = max(hits, key=lambda h: h["words"])
        ent, conf = match.score(
            best, cfg["base"]["list_item"], cfg["section"]["certifications"], index, soc_weights, cfg
        )
        if ent is not None:
            out.update(match.describe(ent, index), confidence=conf)
    # Not in the data: keep it only if it reads like a credential ("NIHSS", "Wound Care Certified"), and is not
    # just an issuer line ("Louisiana State Board of Nursing").
    if out["id"] is None and not (ACRONYM.search(name) or CREDENTIAL_WORD.search(name) and len(name.split()) > 1):
        return None
    if out["id"] is None and ISSUER.search(name) and not acro:
        return None
    # Unlinked, and shaped like a heading ("KEY STRENGTHS") or a sentence listing several things.
    if out["id"] is None and (
        name.isupper() and len(name.split()) > 1 and not CREDENTIAL_WORD.search(name) or len(rest) >= 3
    ):
        return None
    # Unlinked, and a degree or school line: "Associate Degree in Nursing (ADN) | ... College". A bare "Certificate"
    # is also a degree in the data, so only a longer or acronym degree counts ("Critical Care Certificate" stays).
    degree = any(h["words"] > 1 or h["cased"] for h in match.find(item, index, {"degree"}))
    if out["id"] is None and (degree or SCHOOL_WORDS.search(item)):
        return None
    return out


def license_key(name):
    """Comparable license name: "registered nurse license", "RN Licensure" and "Registered Nurse" are one license."""
    return " ".join(w for w in match.norm(name).split() if w not in ("license", "licensure", "licensed", "state"))


def per_state(cred, item):
    """'Registered Nurse State of California and Texas' is one license per state."""
    states = list(dict.fromkeys(STATES[s] for s in STATE_NAME.findall(item)))
    if cred["kind"] != "license" or len(states) < 2:
        return [cred]
    return [{**cred, "state": s} for s in states]


# ---------- skills ----------


def skill_items(lines):
    """Items of a skills section, split on its most common delimiter."""
    text_lines = paragraphs(lines)
    # Includes mid-line bullets and tabs: "∙ Microsoft Office\t∙ Customer Service\t∙ Training".
    counts = {d: sum(l.count(d) for l in text_lines) for d in ";,|•∙·●▪\t"}
    delim = max(counts, key=counts.get)
    if counts[delim] == 0:
        return [LABEL.sub("", l) for l in text_lines]
    items = []
    # "(Word, Excel)" lists items; "(29 CFR 1910/1926)" does not.
    inner_sep = re.compile(r"[,;]|(?<!\d)/|/(?!\d)")
    for line in text_lines:
        line = LABEL.sub("", line)
        for item in split_outside_parens(line, delim):
            m = re.match(r"(.*?)\s*\((.+)\)\s*$", item)
            if m and inner_sep.search(m.group(2)):
                items.append(m.group(1))
                items.extend(p.strip() for p in inner_sep.split(m.group(2)) if p.strip())
            else:
                items.append(item)
    return items


CLAUSE_VERBS = {
    "maintain",
    "ensure",
    "provide",
    "support",
    "improve",
    "promote",
    "assist",
    "help",
    "facilitate",
    "deliver",
    "manage",
    "perform",
    "conduct",
    "develop",
    "coordinate",
    "monitor",
    "educate",
    "assess",
    "administer",
    "lead",
    "oversee",
    "collaborate",
    "communicate",
    "create",
    "implement",
    "review",
}
LIST_LEAD = re.compile(r"^(?:and|or|including|includes|include|such as|e\.g\.|i\.e\.|plus|as well as)\s+", re.I)


def inline_lists(text, generic_heads):
    """Items of a comma list inside a sentence: 'suturing, splinting, IV hydration, and EKGs' -> 4 items."""
    out = []
    for clause in re.split(r"[.;:!?](?:\s|$)|\s[–—]\s", text):
        parts = split_outside_parens(clause, ",")
        if len(parts) < 3:
            continue
        # The first part carries the sentence's lead-in ("Practice consisted of primary care"); keep its tail.
        head = re.split(r"\b(?:of|including|in|with|such as|on|for|performing|providing)\s+", parts[0])[-1]
        tail = re.split(r"\s+(?:and|or)\s+", parts[-1])
        items = [head] + parts[1:-1] + tail
        items = [LIST_LEAD.sub("", re.sub(r"\s*\betc\.?$", "", i)).strip(" .") for i in items]
        if sum(1 <= len(i.split()) <= 4 for i in items) < 3:
            continue
        for item in items:
            words = item.split()
            if not 1 <= len(words) <= 4 or not re.search(r"[A-Za-z]{2}", item):
                continue
            if words[0].lower().endswith("ed") or words[-1].lower() in generic_heads:
                continue  # "administered medications" is a clause; "physicians" are people
            if len(words) > 1 and (words[0].lower().endswith("ing") or words[0].lower() in CLAUSE_VERBS):
                continue  # "ordering diagnostic tests", "maintain safe patient care" are clauses, not skills
            out.append(item)
    return out


def action_objects(texts, generic_heads, fillers):
    """Noun phrases a bullet's verb acts on ('performed X', 'built Y in Z') or that someone is 'skilled in'."""
    # Bullets start with a bare verb that spaCy reads as a noun; a subject in front fixes the parse.
    docs = nlp().pipe("They " + t[0].lower() + t[1:] for t in texts if t)
    out = []
    for doc in docs:
        for ch in doc.noun_chunks:
            head = ch.root
            while head.dep_ == "conj" and head.head is not head:
                head = head.head
            prep = head.head if head.dep_ == "pobj" else None
            if not (
                head.dep_ in ("dobj", "obj")
                or prep is not None
                and prep.lower_ in OBJECT_PREPS
                and prep.head.pos_ == "VERB"
                or prep is not None
                and prep.head.lower_ in SKILL_LEAD
            ):
                continue
            part = []
            for t in list(ch) + [None]:
                if t is None or t.pos_ == "CCONJ":
                    # Numbers go, except inside a hyphenated word ("third-party", "12-lead").
                    words = [
                        w
                        for w in part
                        if w.pos_ not in ("DET", "PRON", "SYM")
                        and not ((w.pos_ == "NUM" or w.like_num) and w.whitespace_)
                    ]
                    # Strip leading filler, but not the first half of a hyphenated word ("well-child").
                    while words and (
                        len(words[0]) == 1
                        and words[0].is_alpha
                        or words[0].whitespace_
                        and (words[0].is_stop or words[0].pos_ in ("ADV", "VERB", "PUNCT"))
                    ):
                        words = words[1:]
                    if len(words) > 1 and words[-1].lower_ in generic_heads:
                        words = words[:-1]
                    while len(words) > 2 and words[0].lower_ in fillers and words[0].whitespace_:
                        words = words[1:]
                    if (
                        words
                        and len(words) <= 5
                        and words[-1].pos_ in ("NOUN", "PROPN")
                        and not any(w.text in "()[]" for w in words)
                    ):
                        out.append(doc[words[0].i : words[-1].i + 1].text)
                    part = []
                else:
                    part.append(t)
    return out


class Skills:
    """Collects skill candidates, keeps the best confidence per skill."""

    def __init__(self, index, cfg, soc_weights):
        self.index, self.cfg, self.soc_weights = index, cfg, soc_weights
        self.stop = {match.norm(s) for s in cfg["stoplist"]}
        self.items = {}

    def add(self, text, method, section, hit=None):
        cfg = self.cfg
        base, section_w = cfg["base"][method], cfg["section"].get(section, cfg["section"]["other"])
        text = BULLET.sub("", re.sub(r"\s+as needed$", "", text)).strip(" |,;:–-")
        key = match.norm(text)
        # The stoplist is for generic words in running text; "Training" in a skills list is a claimed skill.
        stopped = key in self.stop and method != "list_item"
        if not key or stopped or self.has_type(key, {"language"}) or text in STATES or text in STATES.values():
            return
        if not re.search(r"[a-z]", key):
            return  # "1926" (from "29 CFR 1910/1926"): a number is not a skill
        if hit and hit["type"] == "specialty" and self.has_type(key, {"title", "license"}):
            return  # "Registered Nurse" is a role, not a practice area skill
        item = {
            "text": text,
            "type": "skill",
            "id": None,
            "label": None,
            "source": None,
            "found_in": section,
            "method": method,
        }
        ent = None
        if hit:
            ent, conf = match.score(hit, base, section_w, self.index, self.soc_weights, cfg)
            # One data word in running text ("exercise", "cholesterol") counts only if it fits the occupation.
            if ent is not None and (
                hit["words"] == 1 and section != "skills" and match.coherence(ent, self.index, self.soc_weights) == 0
            ):
                ent = None
        # Running text yields fragments ("mechanical", "process hazards"); without a data link only an item someone
        # listed in a skills section ("Word, Excel, PowerPoint") counts.
        if ent is None and method != "list_item":
            return
        if ent is not None:
            item.update(match.describe(ent, self.index), type=self.index["ents"][ent][0], confidence=conf)
            key = ("ent", ent)
        else:
            spec = cfg["unlinked_spec"][min(len(key.split()), len(cfg["unlinked_spec"])) - 1]
            item["confidence"] = round(base * spec * section_w, 2)
        old = self.items.get(key)
        if old is None or item["confidence"] > old["confidence"]:
            self.items[key] = item

    def has_type(self, key, types):
        entry = self.index["phrases"].get(key)
        return bool(entry) and any(self.index["ents"][e][0] in types for e, _ in entry[1])

    def add_hits(self, text, method, section):
        for h in match.find(text, self.index, set(SKILL_ORDER), SKILL_ORDER):
            # A bullet's first word is its verb ("Act as ...", "Lead ..."), not the product of the same name.
            if h["words"] == 1 and text.lstrip().startswith(h["text"]):
                continue
            self.add(h["text"], method, section, h)

    def result(self):
        seen, out = set(), []
        for item in sorted(self.items.values(), key=lambda i: -i["confidence"]):
            k = match.norm(item["text"])
            if item["confidence"] >= self.cfg["min_confidence"] and k not in seen:
                seen.add(k)
                out.append(item)
        return out


# ---------- the whole resume ----------


class InputTooLargeError(ValueError):
    """The text is longer than config.toml's [limits] max_chars; no resume is that long."""


def parse(text, index, cfg, today):
    mcfg = cfg["match"]
    limit = cfg["limits"]["max_chars"]
    if len(text) > limit:
        raise InputTooLargeError(f"text has {len(text):,} characters; the limit is {limit:,} ([limits] max_chars)")
    text = text.replace("\r", "")
    sections = split_sections(text, cfg)
    by_name, experience_lines = defaultdict(list), []
    for name, lines in sections:
        by_name[name].extend(l for l in lines if l)
        if name == "experience":
            experience_lines += lines + [""]

    # Once an unheaded summary paragraph starts in the top block, the rest of the block is that paragraph.
    top = by_name["top"]
    first_prose = next((i for i, l in enumerate(top) if is_prose(l)), len(top))
    out = contact_block(top[: max(1, first_prose)], text, index)
    out["phones"] = phones(sections)
    out["phone"] = out["phones"][0]["number"] if out["phones"] else None
    if not out["location"]:
        out["location"] = next(
            (loc for line in by_name["location"] for loc in [find_location(line, index)[0]] if loc), None
        )
    out["job_title"] = by_name["job_title"][0] if by_name["job_title"] else None
    out["industry"] = by_name["industry"][0] if by_name["industry"] else None
    # No summary header (a bare paragraph, or a resume with its line breaks lost): the top block's prose is it.
    summary = " ".join(paragraphs(by_name["summary"])) or " ".join(top[first_prose:])
    m = CLAIMED_YEARS.search(summary)
    out["summary"] = summary or None
    out["claimed_years"] = int(m.group(1)) if m else None

    blocks = entry_blocks(unzip_columns(tidy_experience(experience_lines, out["name"])))
    jobs = [parse_job(e, index, today) for e in blocks]
    intervals = [j.pop("_interval") for j in jobs]
    out["experience"] = jobs
    out["total_experience_months"] = total_months([i for i in intervals if i])
    # "EDUCATION & CREDENTIALS": lines without a degree that name a credential belong to the credentials.
    edu_lines, edu_creds = [], []
    for line in by_name["education"]:
        is_cred = not match.find(line, index, {"degree"}) and (
            match.find(line, index, {"license", "cert"}) or CREDENTIAL_WORD.search(line)
        )
        (edu_creds if is_cred else edu_lines).append(line)
    out["education"] = parse_education(edu_lines, index)

    mixed = skill_items(by_name["certifications_skills"])
    mixed_creds = [i for i in mixed if match.find(i, index, {"license", "cert"}) and looks_like_credential(i)]
    mixed_skills = [i for i in mixed if i not in mixed_creds]
    cred_items = credential_items(by_name["certifications"] + edu_creds, index) + mixed_creds
    soc_weights = occupation_weights(jobs, out, cred_items, index)
    groups = match.group_weights(soc_weights)
    out["occupation_group"] = (
        {"code": f"{groups[0][0]}-0000", "title": cfg["occupation_groups"].get(groups[0][0])} if groups else None
    )
    top_group = groups[0][0] if groups else None
    out["occupations"] = [
        index["soc_titles"].get(s)
        for s, _ in sorted(soc_weights.items(), key=lambda x: -x[1])
        if s[:2] == top_group and index["soc_titles"].get(s)
    ][:3]

    creds, seen = [], set()
    for item in cred_items:
        c = parse_credential(item, index, mcfg, soc_weights)
        for c in per_state(c, item) if c else []:
            same = license_key(c["label"] or c["name"]) if c["kind"] == "license" else c["id"] or match.norm(c["name"])
            key = (same, c["state"])
            if key not in seen:
                seen.add(key)
                creds.append(c)
    pairs = match.acronym_pairs(text)
    # "CCRN certified" or "Iowa PA license #..." read as a title still states the credential.
    job_titles = sorted(
        {j["title"] for j in jobs if j["title"] and not MENTION_WORD.search(j["title"])}, key=len, reverse=True
    )
    creds += mentioned_credentials(text, sections, creds, index, mcfg, soc_weights, pairs, job_titles)
    out["licenses"] = [c for c in creds if c.pop("kind") == "license"]
    out["certifications"] = [c for c in creds if c not in out["licenses"]]
    out["acronyms"] = pairs

    langs, skills = languages(by_name["languages"], text, index, cfg)
    out["languages"] = langs

    sk = Skills(index, mcfg, soc_weights)
    lang_keys = {match.norm(l["language"]) for l in langs}
    for item in skill_items(by_name["skills"]) + mixed_skills + skills:
        if match.norm(item) in lang_keys:
            continue
        hits = match.find(item, index, set(SKILL_ORDER), SKILL_ORDER)
        whole = [h for h in hits if match.norm(h["text"]) == match.norm(item)]
        sk.add(item, "list_item", "skills", whole[0] if whole else None)
        for h in hits:
            if h["words"] > 1:  # one generic word inside a longer item ("coordination") is noise
                sk.add(h["text"], "phrase", "skills", h)
    bullets = [b for j in jobs for b in j["bullets"]]
    for b in bullets:
        sk.add_hits(b, "phrase", "experience")
    sk.add_hits(summary, "phrase", "summary")
    generic = set(mcfg["generic_heads"])
    candidates = [(t, "inline_list") for b in bullets + [summary] for t in inline_lists(b, generic)]
    candidates += [
        (t, "action_object") for t in action_objects(bullets + [summary], generic, set(mcfg["filler_adjectives"]))
    ]
    for t, method in candidates:
        if any(match.norm(h["text"]) == match.norm(t) for h in match.find(t, index, {"title"})):
            continue  # "medical assistants" is who they worked with, not a skill
        hit = next(
            (h for h in match.find(t, index, set(SKILL_ORDER), SKILL_ORDER) if match.norm(h["text"]) == match.norm(t)),
            None,
        )
        sk.add(t, method, "experience", hit)
    out["skills"] = sk.result()
    for job in jobs:
        said = f" {match.norm(' '.join(job['bullets']))} "
        job["skills"] = [s["text"] for s in out["skills"] if f" {match.norm(s['text'])} " in said]

    out["specialties"] = specialties(out, jobs, summary, index, mcfg, soc_weights)
    current_job = blocks[0]["head"] if blocks else []
    out["availability"] = availability(by_name["availability"] + [summary] + by_name["top"] + current_job, index)
    out["seniority"] = seniority(jobs, out["headline"], index)
    out["other_sections"] = {n: by_name[n] for n in by_name if n not in HANDLED_SECTIONS}
    out["document"] = document_kind(out, sections)
    return public(out)


def document_kind(out, sections):
    """Whether the text reads as a resume: {"kind": "resume" | "profile_export" | "unknown", "signals": {...}}.

    An invoice or a letter still yields a "name" from its first line; "unknown" tells the caller not to trust it.
    """
    signals = {
        "contact": bool(out["emails"] or out["phones"]),
        "sections": len({n for n, lines in sections if n != "top" and any(lines)}),
        "dated_jobs": sum(bool(j["start"]) for j in out["experience"]),
        "education": len(out["education"]),
    }
    if signals["dated_jobs"] or signals["sections"] >= 2 or signals["sections"] and signals["contact"]:
        kind = "resume"
    elif out["job_title"] or out["industry"]:
        kind = "profile_export"
    else:
        kind = "unknown"
    return {"kind": kind, "signals": signals}


INTERNAL_FIELDS = ("id", "source", "method", "found_in", "socs")


def public(out):
    """Drop the fields the parser uses internally (data ids, sources, how a skill was found, SOC codes)."""
    for field in ("experience", "skills", "licenses", "certifications", "specialties"):
        out[field] = [{k: v for k, v in item.items() if k not in INTERNAL_FIELDS} for item in out[field]]
    return out


def occupation_weights(jobs, top, cred_items, index):
    """O*NET-SOC codes the resume points at, weighted 0..1 (recent titles count most)."""
    w = defaultdict(float)
    for rank, job in enumerate(jobs):
        for soc in job["socs"]:
            w[soc] += 1.0 / (1 + rank) / len(job["socs"])
    licenses = [h for item in cred_items for h in match.find(item, index, {"license"})]
    licenses += [h for c in top["credentials"] for h in match.find(c, index, {"license"})]
    for h in licenses:
        socs = {s for e in h["ents"] for s in index["socs"].get(e, ())}
        for soc in socs:
            w[soc] += 0.8 / len(socs)
    top_w = max(w.values(), default=1.0)
    return {s: v / top_w for s, v in w.items()}


def mentioned_credentials(text, sections, creds, index, cfg, soc_weights, pairs, job_titles):
    """Licenses and certifications named outside the credentials section (summary, post-nominals, bullets).

    A job title is skipped: "Pediatric Home Care LPN" is the role held, not a credential stated.
    """
    have = {c["id"] for c in creds if c["id"]} | {c["acronym"] for c in creds if c["acronym"]}
    licensed = {license_key(c["label"] or c["name"]) for c in creds if c["kind"] == "license"}
    stop_acronyms = set(cfg["running_text_acronym_stoplist"])
    found = {}
    for name, lines in sections:
        if name in ("certifications", "education"):
            continue
        for line in lines:
            if name == "experience":
                for title in job_titles:
                    line = line.replace(title, " ")
            hits = match.find(line, index, {"license", "cert"})
            acronyms = sum(h["cased"] and len(h["text"]) >= 3 for h in hits)
            # The top block lists credentials ("License #: RN-... | ACLS, BLS, PALS"); a whole part is a list item.
            listed = {match.norm(p) for p in re.split(r"[|,;]", line)} if name == "top" else set()
            for h in hits:
                # Running text names many certification topics ("general surgery", "family medicine"); only an
                # acronym ("ACLS") or a name that itself says credential ("Basic Life Support") counts.
                if not (h["cased"] and len(h["text"]) >= 3 or h["words"] >= 2 and MENTION_WORD.search(h["text"])):
                    continue
                if re.search(re.escape(h["text"]) + r"-[a-z]", line) or h["text"] in stop_acronyms:
                    continue  # "CRM-style tracking": a modifier; "EMR": usually the record system, not a credential
                if h["cased"] and h["text"] in pairs and not CREDENTIAL_WORD.search(pairs[h["text"]]):
                    continue  # the resume defines it as something else: "Chronic Care Management (CCM)"
                base = cfg["base"]["list_item" if match.norm(h["text"]) in listed else "phrase"]
                ent, conf = match.score(
                    h, base, cfg["section"].get(name, cfg["section"]["other"]), index, soc_weights, cfg
                )
                if ent is None or conf < cfg["min_confidence"]:
                    continue
                # An acronym in running text (EMR, CVS, PPE) counts when it fits this person's occupation, sits
                # on a line about credentials ("BLS Certification"), or next to other credentials ("ACLS, BLS").
                in_context = CREDENTIAL_WORD.search(line) or acronyms > 1
                if h["cased"] and name != "top" and not in_context and match.coherence(ent, index, soc_weights) == 0:
                    continue
                d = match.describe(ent, index)
                lkey = license_key(d["label"])
                if (
                    d["id"] in have
                    or h["text"] in have
                    or d["id"] in found
                    or h["type"] == "license"
                    and lkey in licensed
                ):
                    continue
                if h["type"] == "license":
                    licensed.add(lkey)
                found[d["id"]] = {
                    "name": h["text"],
                    "acronym": h["text"] if h["cased"] else None,
                    "issuer": None,
                    "state": None,
                    "status": None,
                    "year": None,
                    "number": None,
                    "kind": h["type"],
                    **d,
                    "confidence": conf,
                }
    return list(found.values())


def languages(lines, text, index, cfg):
    """Languages with proficiency; items in a 'Languages' section that are not languages go back as skills."""
    prof_words = cfg["languages"]["proficiency"]
    prof_re = re.compile(r"\b(" + "|".join(map(re.escape, prof_words)) + r")\b", re.I)
    out, not_langs = {}, []
    for item in skill_items(lines) if lines else []:
        hits = match.find(item, index, {"language"})
        if not hits:
            not_langs.append(item)
        for h in hits:
            p = prof_re.search(item)
            out.setdefault(index["ents"][h["ents"][0]][2], p.group(1).lower() if p else None)
    for line in text.splitlines():
        for h in match.find(line, index, {"language"}):
            p = prof_re.search(line)
            if h["text"][0].isupper():
                out.setdefault(index["ents"][h["ents"][0]][2], p.group(1).lower() if p else None)
    return [{"language": k, "proficiency": v} for k, v in out.items()], not_langs


def specialties(out, jobs, summary, index, cfg, soc_weights):
    found = {}
    texts = [("top", h) for h in out["headline"]] + [("experience", j["title"] or "") for j in jobs]
    texts += [("summary", summary)]
    for section, t in texts:
        for h in match.find(t, index, {"specialty"}):
            ent, conf = match.score(
                h, cfg["base"]["phrase"], cfg["section"].get(section, cfg["section"]["other"]), index, soc_weights, cfg
            )
            if ent is None or conf < cfg["min_confidence"]:
                continue
            d = match.describe(ent, index)
            if d["id"] not in found or found[d["id"]]["confidence"] < conf:
                found[d["id"]] = {"text": h["text"], **d, "confidence": conf}
    return sorted(found.values(), key=lambda s: -s["confidence"])


AVAILABILITY_TYPES = {"work_mode": "work_mode", "shift": "shifts", "employment_type": "employment_type"}


def availability(lines, index):
    """Work mode, shifts and employment type named in these lines: {"work_mode": ["onsite"], "shifts": ["day"], ...}."""
    out = {field: [] for field in AVAILABILITY_TYPES.values()}
    for line in lines:
        for h in match.find(line, index, set(AVAILABILITY_TYPES)):
            label = index["ents"][h["ents"][0]][2]
            field = out[AVAILABILITY_TYPES[h["type"]]]
            if label not in field:
                field.append(label)
    return out


def seniority(jobs, headline, index):
    """Seniority level ("senior", "manager", ...) of the most recent job title, else of the headline."""
    for text in [j["title"] for j in jobs[:1] if j["title"]] + headline:
        hits = match.find(text, index, {"seniority"})
        if hits:
            return index["ents"][max(hits, key=lambda h: h["words"])["ents"][0]][2]
    return None
