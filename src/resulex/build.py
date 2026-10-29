"""Compile the vocab/ JSON files into one pickled index."""

import json
import math
import os
import pickle
import re
from collections import defaultdict

from .match import SKILL_TYPES, case_key, config_hash, norm, norm_tok, tokens, vocab_stamp

MAX_WORDS = 12


class Builder:
    def __init__(self, cfg):
        self.cfg = cfg
        self.ents, self.ent_ids = [], {}
        self.socs, self.attrs = defaultdict(set), {}
        self.phrases = defaultdict(dict)
        self.rel = defaultdict(dict)
        self.stop = {norm(s) for s in cfg["match"]["stoplist"]}
        self.nominal = cfg.get("build", {}).get("nominalize", {})
        self.nominal_types = set(cfg.get("build", {}).get("nominalize_types", []))
        self.vendors = cfg.get("build", {}).get("vendor_prefixes", [])
        self.vendor_types = set(cfg.get("build", {}).get("vendor_types", []))

    def entity(self, etype, eid, label, source):
        key = (etype, eid)
        if key not in self.ent_ids:
            self.ent_ids[key] = len(self.ents)
            self.ents.append((etype, eid, label, source))
        return self.ent_ids[key]

    def add(self, etype, row):
        """One vocab entity: {id, label, source, aliases, cased, socs, attrs}."""
        ent = self.entity(etype, row["id"], row["label"], row["source"])
        for a in row.get("aliases", []):
            self.alias(ent, a, False)
        for a in row.get("cased", []):
            self.alias(ent, a, True)
        for soc, w in row.get("socs", {}).items():
            self.socs[ent].add(soc)
            self.rel[soc][ent] = max(w, self.rel[soc].get(ent, 0.0))
        if row.get("attrs"):
            self.attrs[ent] = row["attrs"]

    def alias(self, ent, text, cased, derived=False):
        if text.startswith("re:"):
            return  # regex aliases (keywords.json) are for job descriptions; plain aliases cover resumes
        # "Registered Nurse (RN)" is also written "Registered Nurse" and "RN".
        m = re.fullmatch(r"(.+?)\s*\(([^()]+)\)\s*", text)
        if m:
            self.alias(ent, m.group(1), cased)
            self.alias(ent, m.group(2), cased)
        toks = [t for t, _, _ in tokens(text)]
        key = " ".join(norm_tok(t) for t in toks)
        if not toks or len(toks) > MAX_WORDS or len(key) < 2:
            return
        if self.ents[ent][0] in SKILL_TYPES and key in self.stop:
            return
        letters = re.sub(r"[^A-Za-z]", "", text)
        surface = case_key(toks) if cased or (letters.isupper() and len(letters) <= 6) else None
        prev = self.phrases[key].get(ent, surface)
        self.phrases[key][ent] = None if prev is None or surface is None else surface
        if derived:
            return  # a generated form is not expanded again ("control design" <-> "design control" would loop)
        if surface is None and self.ents[ent][0] in self.nominal_types:
            noun = nominalize(text, self.nominal)
            if noun:
                self.alias(ent, noun, False, derived=True)
        # "Microsoft Excel" is written "Excel"; a one-word remainder must match in exact case ("Access", not "access").
        vendor = next((v for v in self.vendors if text.startswith(v + " ")), None)
        if vendor and self.ents[ent][0] in self.vendor_types:
            rest = text[len(vendor) + 1 :]
            if 1 <= len(rest.split()) <= 3:
                self.alias(ent, rest, cased or len(rest.split()) == 1, derived=True)

    def specificity(self):
        """Rarer and longer phrases score higher; 'health' (inside thousands of phrases) scores low."""
        m = self.cfg["match"]
        df = defaultdict(int)
        for key in self.phrases:
            words = key.split()
            subs = {
                " ".join(words[i : i + n]) for n in range(1, min(4, len(words)) + 1) for i in range(len(words) - n + 1)
            }
            subs.add(key)
            for s in subs:
                if s in self.phrases:
                    df[s] += 1
        total = len(self.phrases)
        out = {}
        for key, ents in self.phrases.items():
            if not ents:
                continue
            rarity = 1 - math.log(df[key]) / math.log(total)
            spec = min(1.0, m["spec_a"] + m["spec_b"] * (len(key.split()) - 1) + m["spec_c"] * rarity)
            out[key] = (round(spec, 3), tuple(ents.items()))
        return out


def ent_groups(rel):
    """O*NET major groups ('29', '43', ...) each entity is linked to, through any of its occupations."""
    out = defaultdict(set)
    for soc, ents in rel.items():
        for e in ents:
            out[e].add(soc[:2])
    return {e: frozenset(g) for e, g in out.items()}


CONNECTORS = {"to", "for", "in", "on", "with", "of", "the", "a", "an", "and", "or", "from", "by", "at", "into", "as"}


def nominalize(text, table):
    """'administer medication' -> 'medication administration', the way resumes phrase it."""
    words = text.split()
    verb = words[0].lower() if words else ""
    if verb not in table or not 2 <= len(words) <= 4 or any(w.lower() in CONNECTORS for w in words[1:]):
        return None
    return " ".join(words[1:] + [table[verb]])


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build(config_path):
    import tomllib

    with open(config_path, "rb") as f:
        raw = f.read()
    cfg = tomllib.loads(raw.decode())
    base = os.path.dirname(os.path.abspath(config_path))
    vocab = os.path.join(base, cfg["vocab"]["dir"])
    b = Builder(cfg)
    # Per type, our curated file loads before the imported one, so a curated label wins for a shared id.
    for etype in cfg["vocab"]["types"]:
        for part in ("curated", "imported"):
            path = os.path.join(vocab, part, f"{etype}.json")
            if os.path.exists(path):
                rows = load(path)["entities"]
                for row in rows:
                    b.add(etype, row)
                print(f"{part}/{etype}.json: {len(rows)} entities")
    for part in ("curated", "imported"):
        path = os.path.join(vocab, part, "removals.json")
        for etype, aliases in (load(path)["removals"] if os.path.exists(path) else {}).items():
            for a in aliases:
                for ent in [e for e in b.phrases.get(norm(a), {}) if b.ents[e][0] == etype]:
                    del b.phrases[norm(a)][ent]

    phrases = b.specificity()
    # How many skill phrases end in each word: "assessment", "care", "testing" are typical skill heads.
    skill_heads = defaultdict(int)
    for key, (_, ents) in phrases.items():
        if any(b.ents[e][0] in SKILL_TYPES | {"specialty"} for e, _ in ents):
            skill_heads[key.split()[-1]] += 1
    max_len = {}
    for key in phrases:
        words = key.split()
        max_len[words[0]] = max(max_len.get(words[0], 0), len(words))
    zips = {z: tuple(p) for z, p in load(os.path.join(vocab, "imported", "places.json"))["places"].items()}
    index = {
        "config_hash": config_hash(raw.decode()),
        "vocab_stamp": vocab_stamp(vocab),
        "ents": b.ents,
        "socs": {e: tuple(sorted(s)) for e, s in b.socs.items()},
        "attrs": b.attrs,
        "phrases": phrases,
        "max_len": max_len,
        "skill_heads": dict(skill_heads),
        "rel": dict(b.rel),
        "ent_groups": ent_groups(b.rel),
        "soc_titles": {e[1]: e[2] for e in b.ents if e[0] == "title" and re.fullmatch(r"\d\d-\d{4}\.\d\d", e[1])},
        "zips": zips,
        "places": {(c.lower(), s) for c, s in zips.values()},
    }
    out = os.path.join(base, cfg["index"])
    with open(out, "wb") as f:
        pickle.dump(index, f, protocol=5)
    print(
        f"{len(b.ents)} entities, {len(phrases)} phrases, {len(b.rel)} occupations -> {out} "
        f"({os.path.getsize(out) / 1e6:.0f} MB)"
    )
