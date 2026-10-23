"""Turn raw reference data into vocab/imported/*.json, the files build.py reads.

    uv run python tools/import_vocab.py --raw ../data

Run it only when the raw data changes (a new O*NET release, an edited mapping in tools/import.toml).
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
import tomllib
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from match import norm  # noqa: E402  (same normalization the parser uses for default ids)

csv.field_size_limit(sys.maxsize)
NULLS = {"", "n/a", "na", "null", "none"}
SQL_VALUE = re.compile(r"'((?:[^']|'')*)'|TO_DATE\('([^']*)',\s*'[^']*'\)|(NULL)|(-?\d+(?:\.\d+)?)")


# ---------- raw readers ----------


def walk(obj, path):
    """Values at a dotted path; `key[*]` steps into a list. "$" is the object itself."""
    cur = [obj]
    if path == "$":
        return cur
    for part in path.split("."):
        star = part.endswith("[*]")
        key = part[:-3] if star else part
        nxt = []
        for c in cur:
            v = c.get(key) if isinstance(c, dict) else None
            if v is None:
                continue
            if star:
                nxt.extend(v)
            else:
                nxt.append(v)
        cur = nxt
    return cur


def walk_records(obj, path):
    """Records at a path where `{name}` steps into every value of a dict and keeps its key as field `name`.

    "Occupation.{soc}.Skill.{label}" -> [{"soc": "29-1141.00", "label": "EKG", "_value": [aliases...]}, ...]
    """
    cur = [({}, obj)]
    for part in path.split("."):
        m = re.fullmatch(r"\{(\w+)\}", part)
        nxt = []
        for ctx, c in cur:
            if m:
                if isinstance(c, dict):
                    nxt.extend(({**ctx, m.group(1): k}, v) for k, v in c.items())
            else:
                nxt.extend((ctx, v) for v in walk(c, part))
        cur = nxt
    return [{**ctx, **v} if isinstance(v, dict) else {**ctx, "_value": v} for ctx, v in cur]


_json_cache = {}


def load_json(path):
    """Parsed JSON, cached: several sources read the same 12 MB file."""
    if path not in _json_cache:
        with open(path, encoding="utf-8") as f:
            _json_cache[path] = json.load(f)
    return _json_cache[path]


def values(rec, field, sep=None):
    out = []
    for v in walk(rec, field):
        for s in str(v).split(sep) if sep else [str(v)]:
            s = s.strip()
            if s.lower() not in NULLS:
                out.append(s)
    return out


def read_sql(path, table):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    for chunk in re.split(r"\nInsert into ", text)[1:]:
        name, rest = chunk.split(None, 1)
        if name != table:
            continue
        cols_part, vals_part = rest.split("Values", 1)
        cols = [c.strip() for c in cols_part.strip().strip("()").split(",")]
        vals = []
        for m in SQL_VALUE.finditer(vals_part):
            s, d, null, num = m.groups()
            vals.append(s.replace("''", "'") if s is not None else d if d is not None else None if null else num)
        if len(vals) != len(cols):
            sys.exit(f"{path}: insert has {len(cols)} columns but {len(vals)} values near: {chunk[:120]!r}")
        yield dict(zip(cols, vals))


def read_xlsx(path, header_row):
    import openpyxl  # only the crosswalk needs it

    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
    rows = ws.iter_rows(values_only=True)
    for _ in range(header_row - 1):
        next(rows)
    header = [str(h).strip() for h in next(rows)]
    for row in rows:
        yield {h: ("" if v is None else str(v)) for h, v in zip(header, row)}


def read_rows(src, raw):
    path = os.path.join(raw, src["path"])
    fmt = src["format"]
    if fmt in ("tsv", "csv"):
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            kw = {"delimiter": "\t", "quoting": csv.QUOTE_NONE} if fmt == "tsv" else {}
            yield from csv.DictReader(f, **kw)
    elif fmt == "json":
        files = sorted(glob.glob(path))
        if not files:
            sys.exit(f"source {src['name']}: no files match {path}")
        records = src.get("records", "$")
        for p in files:
            doc = load_json(p)
            if any(k in doc for k in src.get("skip_if", [])):
                continue
            yield from walk_records(doc, records) if "{" in records else walk(doc, records)
    elif fmt == "sql":
        yield from read_sql(path, src["table"])
    elif fmt == "xlsx":
        yield from read_xlsx(path, src.get("header_row", 1))
    else:
        sys.exit(f"source {src['name']}: unknown format {fmt!r}")


def keep(rec, src):
    return all((rec.get(f["field"]) or "").strip() not in f["not_in"] for f in src.get("filters", []))


def resolve_socs(rec, src, lookups):
    socs = values(rec, src["soc"]) if "soc" in src else []
    for name in src.get("soc_via", []):
        socs = [v for s in socs for v in lookups[name].get(s, [])]
    return socs


def read_lookup(lk, raw):
    table = defaultdict(list)
    for rec in read_rows(lk, raw):
        k, v = (rec.get(lk["key"]) or "").strip(), (rec.get(lk["value"]) or "").strip()
        if k and v:
            table[k].append(v)
    return table


# ---------- our vocab ----------


class Vocab:
    """Entities keyed by (type, id); the first label and source seen for an id are kept."""

    def __init__(self):
        self.ents = {}
        self.removals = defaultdict(list)

    def entity(self, etype, eid, label, source):
        key = (etype, eid)
        if key not in self.ents:
            self.ents[key] = {
                "id": eid,
                "label": label,
                "source": source,
                "aliases": {},
                "cased": {},
                "socs": {},
                "attrs": {},
            }
        return self.ents[key]

    def add_source(self, src, lookups, raw):
        etype, sep = src["entity"], src.get("alias_sep")
        for rec in read_rows(src, raw):
            if not keep(rec, src):
                continue
            labels = values(rec, src["label"])
            if src.get("action") == "remove":
                self.removals[etype].extend(labels)
                continue
            socs = resolve_socs(rec, src, lookups)
            row_cased = str(rec.get(src.get("cased_flag", ""), "")).lower() == "true"
            ids = values(rec, src["id"]) if "id" in src else []
            for label in labels:
                e = self.entity(etype, ids[0] if ids else norm(label), label, src["name"])
                plain = [label] + [a for f in src.get("aliases", []) for a in values(rec, f, sep)]
                exact = [a for f in src.get("cased", []) for a in values(rec, f, sep)]
                for a in plain:
                    e["cased" if row_cased else "aliases"][a] = None
                for a in exact:
                    e["cased"][a] = None
                for soc in socs:
                    e["socs"][soc] = 1.0
                if "attrs" in src:
                    e["attrs"] = {k: (values(rec, f) or [None])[0] for k, f in src["attrs"].items()}

    def add_relation(self, r, lookups, raw):
        weights = r["weights"]
        for rec in read_rows(r, raw):
            e = self.ents.get((r["entity"], (rec.get(r["id"]) or "").strip()))
            w = weights.get((rec.get(r["weight"]) or "").strip(), 0.0)
            if e is None or not w:
                continue
            for soc in resolve_socs(rec, r, lookups):
                e["socs"][soc] = max(w, e["socs"].get(soc, 0.0))

    def files(self):
        """{type: [entity, ...]} with empty fields left out."""
        out = defaultdict(list)
        for (etype, _), e in self.ents.items():
            row = {"id": e["id"], "label": e["label"], "source": e["source"]}
            for field in ("aliases", "cased"):
                if e[field]:
                    row[field] = list(e[field])
            if e["socs"]:
                row["socs"] = e["socs"]
            if e["attrs"]:
                row["attrs"] = e["attrs"]
            out[etype].append(row)
        return out


def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  {os.path.relpath(path)}  {os.path.getsize(path) / 1e6:.1f} MB")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", required=True, help="folder with the raw reference data")
    ap.add_argument("--mapping", default=os.path.join(HERE, "import.toml"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(HERE), "vocab", "imported"))
    args = ap.parse_args()
    with open(args.mapping, "rb") as f:
        cfg = tomllib.load(f)

    v = Vocab()
    lookups = {lk["name"]: read_lookup(lk, args.raw) for lk in cfg.get("lookup", [])}
    for src in cfg["source"]:
        n = len(v.ents)
        v.add_source(src, lookups, args.raw)
        print(f"source {src['name']}: +{len(v.ents) - n} entities")
    for r in cfg.get("relation", []):
        v.add_relation(r, lookups, args.raw)
        print(f"relation {r['name']}")

    os.makedirs(args.out, exist_ok=True)
    for etype, rows in v.files().items():
        write(os.path.join(args.out, f"{etype}.json"), {"type": etype, "entities": rows})
    write(os.path.join(args.out, "removals.json"), {"removals": dict(v.removals)})
    with open(os.path.join(args.raw, cfg["places"]), encoding="utf-8") as f:
        places = {z: p.split("|") for z, p in json.load(f)["places"].items()}
    write(os.path.join(args.out, "places.json"), {"places": places})


if __name__ == "__main__":
    main()
