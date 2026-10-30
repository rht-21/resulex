"""Tokenizer shared with build.py, index lookup, acronym pairs and confidence scoring."""

import hashlib
import os
import pickle
import re

TOKEN = re.compile(r"[A-Za-z0-9]+(?:[.+#][A-Za-z0-9]+)*[+#]*|&")
# Phrases never match across these.
BREAKS = re.compile(r"[;,|•()\[\]:!?]|\.\s")
# When a phrase maps to several entity types, the first type here wins.
TYPE_ORDER = [
    "language",
    "license",
    "cert",
    "degree",
    "specialty",
    "title",
    "org",
    "tech",
    "tool",
    "skill",
    "seniority",
    "work_mode",
    "shift",
    "employment_type",
]
SKILL_TYPES = {"tech", "tool", "skill"}
# Skill search also takes practice areas ("wound care", "critical care"), but prefers a skill entry.
SKILL_ORDER = ["tech", "tool", "skill", "specialty"]


def tokens(text):
    return [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(text)]


# British -> American spellings (ESCO is British, US resumes are not). Applied to both sides, so a rare
# over-merge ("four" -> "for") is harmless.
US_SPELLING = [
    ("isation", "ization"),
    ("haem", "hem"),
    ("paed", "ped"),
    ("oedem", "edem"),
    ("anaes", "anes"),
    ("oesoph", "esoph"),
    ("behaviour", "behavior"),
    ("programme", "program"),
    ("licence", "license"),
    ("centre", "center"),
    ("colour", "color"),
    ("favour", "favor"),
    ("labour", "labor"),
]
US_ENDINGS = [("ise", "ize"), ("ised", "ized"), ("ising", "izing"), ("iser", "izer"), ("yse", "yze")]


def norm_tok(tok):
    """Lowercase, American spelling, singular: 'Immunisations' -> 'immunization'."""
    if tok == "&":
        return "and"
    w = tok.lower()
    for gb, us in US_SPELLING:
        if gb in w:
            w = w.replace(gb, us)
    for gb, us in US_ENDINGS:
        if w.endswith(gb) and len(w) > len(gb) + 2:
            w = w[: -len(gb)] + us
            break
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is", "ous")):
        return w[:-1]
    return w


def case_key(toks):
    """Exact-case form for acronym checks, ignoring a plural s ('EKGs' -> 'EKG')."""
    return " ".join(t[:-1] if len(t) > 2 and t.endswith("s") and t[:-1].isupper() else t for t in toks)


def norm(text):
    return " ".join(norm_tok(t) for t, _, _ in tokens(text))


class IndexOutOfDateError(Exception):
    """index.pkl was built from a different config.toml or vocab/."""


def config_hash(config_text):
    return hashlib.sha1(config_text.encode()).hexdigest()


def vocab_stamp(vocab_dir):
    """Fingerprint of the vocab files' paths and contents; not mtimes, which change when a wheel is installed."""
    h = hashlib.sha1()
    for root, dirs, files in os.walk(vocab_dir):
        dirs.sort()
        for name in sorted(files):
            if name.endswith(".json"):
                path = os.path.join(root, name)
                h.update(os.path.relpath(path, vocab_dir).replace(os.sep, "/").encode() + b"\0")
                with open(path, "rb") as f:
                    h.update(f.read())
    return h.hexdigest()


def load_index(path, config_text, vocab_dir):
    with open(path, "rb") as f:
        index = pickle.load(f)
    if index["config_hash"] != config_hash(config_text) or index.get("vocab_stamp") != vocab_stamp(vocab_dir):
        raise IndexOutOfDateError(f"{path} is out of date with config.toml or vocab/; run: resulex build")
    return index


def find(text, index, types, order=TYPE_ORDER):
    """All longest phrase matches in text whose entities have one of `types`; `order` picks among types."""
    hits = []
    for part in BREAKS.split(text):
        hits.extend(_find_in(part, index, types, order))
    return hits


def _find_in(text, index, types, order):
    toks = tokens(text)
    keys = [norm_tok(t) for t, _, _ in toks]
    phrases, max_len, ents = index["phrases"], index["max_len"], index["ents"]
    hits, i = [], 0
    while i < len(toks):
        hit = None
        for n in range(min(max_len.get(keys[i], 0), len(toks) - i), 0, -1):
            entry = phrases.get(" ".join(keys[i : i + n]))
            if not entry:
                continue
            surface = case_key(t for t, _, _ in toks[i : i + n])
            found = [(e, c) for e, c in entry[1] if (c is None or c == surface) and ents[e][0] in types]
            if found:
                best = min({ents[e][0] for e, _ in found}, key=order.index)
                chosen = [(e, c) for e, c in found if ents[e][0] == best]
                hit = {
                    "text": text[toks[i][1] : toks[i + n - 1][2]],
                    "ents": [e for e, _ in chosen],
                    "type": best,
                    "spec": entry[0],
                    "words": n,
                    # Only the chosen type's aliases: "PALS" is an acronym even though a skill shares its key.
                    "cased": all(c for _, c in chosen),
                }
                break
        if hit:
            hits.append(hit)
            i += hit["words"]
        else:
            i += 1
    return hits


def acronym_pairs(text):
    """Schwartz-Hearst style 'Long Form (ABBR)' pairs defined in the text, as {ABBR: long form}."""
    pairs = {}
    for m in re.finditer(r"([^()\n]{3,120}?)\s*\(([A-Z][A-Za-z0-9&/-]{1,15})\)", text):
        abbr = m.group(2)
        core = re.split(r"[-/]", abbr)[0]
        if sum(c.isupper() for c in core) < 2:
            continue
        before = m.group(1).rstrip(" -–—,")
        long = _long_form(core, before)
        if long:
            # Keep a suffix like "- Spanish" when the abbreviation carries it ("CMI-Spanish").
            pairs[abbr] = before[before.rfind(long) :] if abbr != core else long
    return pairs


def _long_form(short, cand):
    words = cand.split()
    cand = " ".join(words[-min(len(short) + 5, len(short) * 2) :])
    s, l = len(short) - 1, len(cand) - 1
    while s >= 0:
        c = short[s].lower()
        if not c.isalnum():
            s -= 1
            continue
        while l >= 0 and (cand[l].lower() != c or (s == 0 and l > 0 and cand[l - 1].isalnum())):
            l -= 1
        if l < 0:
            return None
        l -= 1
        s -= 1
    start = cand.rfind(" ", 0, l + 1) + 1
    return cand[start:]


def coherence(ent, index, soc_weights):
    """How strongly an entity is linked to the occupations this resume points at (0..1)."""
    best = 0.0
    for soc, w in soc_weights.items():
        best = max(best, w * index["rel"].get(soc, {}).get(ent, 0.0))
    return best


def group_weights(soc_weights):
    """Occupation weights summed per O*NET major group, heaviest first: [('43', 2.1), ('11', 1.0)]."""
    totals = {}
    for soc, w in soc_weights.items():
        totals[soc[:2]] = totals.get(soc[:2], 0.0) + w
    return sorted(totals.items(), key=lambda x: -x[1])


def profile_groups(soc_weights, ratio):
    """The profile's major group, plus any group weighing at least `ratio` of it."""
    ranked = group_weights(soc_weights)
    return {g for g, w in ranked if w >= ratio * ranked[0][1]} if ranked else set()


def in_groups(ent, index, groups):
    """True when the entity belongs to one of the groups, or the data ties it to no occupation at all (e.g. CPR)."""
    linked = index["ent_groups"].get(ent)
    return not linked or bool(linked & groups)


def score(hit, base, section_w, index, soc_weights, cfg):
    """Pick the best entity for a hit, among those of the profile's occupation group; (entity or None, confidence)."""
    groups = profile_groups(soc_weights, cfg["related_group_ratio"])
    ents = [e for e in hit["ents"] if not groups or in_groups(e, index, groups)]
    # The data ties a skill to few occupations ("electronic health record" only to IT and clerical work), so a
    # multi-word skill still links outside the profile's group when it is close to the entity's own label; loose
    # aliases ("state regulations" -> "constitutional law") stay behind the group rule.
    if not ents and not hit["cased"] and hit["words"] > 1 and len(hit["ents"]) == 1:
        ents = [e for e in hit["ents"] if index["ents"][e][0] in SKILL_TYPES and near_label(hit["text"], e, index)]
    if not ents:
        return None, 0.0
    ranked = sorted(((coherence(e, index, soc_weights), e) for e in ents), reverse=True)
    coh, ent = ranked[0]
    # An acronym that names several different things needs the resume's occupation to pick one. Near-identical
    # entries ("Advanced Cardiac Life Support" / "Advanced Cardiovascular Life Support (ACLS) ...") are one thing.
    if hit["cased"] and len(ranked) > 1 and coh == 0 and not same_thing([e for _, e in ranked], index):
        return None, 0.0
    # An exact-case credential acronym ("BLS", "FNP-BC") identifies one thing; its short length is not vagueness.
    spec = (
        cfg["cased_credential_spec"] if hit["cased"] and index["ents"][ent][0] in ("license", "cert") else hit["spec"]
    )
    conf = base * spec * section_w * (1 + cfg["coherence_boost"] * coh)
    return ent, round(min(1.0, conf), 2)


def near_label(text, ent, index):
    """The phrase shares at least 60% of its words with the entity's label."""
    words, label = set(norm(text).split()), set(norm(index["ents"][ent][2]).split())
    return len(words & label) / max(1, len(words)) >= 0.6


def same_thing(ents, index):
    """True when every label shares most of its words with the first one."""
    first = set(norm(index["ents"][ents[0]][2]).split())
    for e in ents[1:]:
        other = set(norm(index["ents"][e][2]).split())
        if len(first & other) / max(1, min(len(first), len(other))) < 0.6:
            return False
    return True


def describe(ent, index):
    etype, eid, label, source = index["ents"][ent]
    return {"id": eid, "label": label, "source": source}
