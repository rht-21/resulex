"""python cli.py build | parse FILE|- [--today YYYY-MM-DD] | eval DIR [--today YYYY-MM-DD]"""

import argparse
import glob
import json
import os
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.toml")

# How eval turns each field into comparable strings.
EVAL_FIELDS = {
    "name": lambda v: [v],
    "email": lambda v: [v],
    "phone": lambda v: [v],
    "location": lambda v: [f"{v.get('city')}, {v.get('state')} {v.get('zip') or ''}".strip()],
    "total_experience_months": lambda v: [v],
    "occupation_group": lambda v: [v["code"]],
    "experience": lambda v: [f"{e.get('title')} @ {e.get('company')} [{e.get('start')}..{e.get('end')}]" for e in v],
    "education": lambda v: [f"{e.get('degree')} @ {e.get('school')}" for e in v],
    "licenses": lambda v: [e["name"] for e in v],
    "certifications": lambda v: [e["name"] for e in v],
    "specialties": lambda v: [e["text"] for e in v],
    "skills": lambda v: [e["text"].lower() for e in v],
    "languages": lambda v: [e["language"] for e in v],
    "availability": lambda v: [f"{field}:{x}" for field, xs in v.items() for x in xs],
}


def load_parser():
    import tomllib

    from . import match, parse

    with open(CONFIG, "rb") as f:
        raw = f.read()
    cfg = tomllib.loads(raw.decode())
    index = match.load_index(os.path.join(HERE, cfg["index"]), raw.decode(), os.path.join(HERE, cfg["vocab"]["dir"]))
    parse.nlp()  # load spaCy up front so parse timings are warm
    return lambda text, today: parse.parse(text, index, cfg, today)


def cmd_parse(args):
    run = load_parser()
    text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    t = time.perf_counter()
    result = run(text, args.today)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"parsed in {(time.perf_counter() - t) * 1000:.0f} ms", file=sys.stderr)


def cmd_eval(args):
    run = load_parser()
    totals = {f: [0, 0, 0] for f in EVAL_FIELDS}  # hit, missed, extra
    times = []
    for txt in sorted(glob.glob(os.path.join(args.dir, "*.txt"))):
        expected_path = txt[:-4] + ".json"
        if not os.path.exists(expected_path):
            print(f"skip {os.path.basename(txt)}: no {os.path.basename(expected_path)}")
            continue
        with open(txt, encoding="utf-8") as f:
            text = f.read()
        with open(expected_path, encoding="utf-8") as f:
            expected = json.load(f)
        t = time.perf_counter()
        got = run(text, args.today)
        times.append((time.perf_counter() - t) * 1000)
        print(f"\n== {os.path.basename(txt)}")
        for field, keys in EVAL_FIELDS.items():
            want = set(map(str, keys(expected[field]))) if expected.get(field) else set()
            have = set(map(str, keys(got[field]))) if got.get(field) else set()
            totals[field][0] += len(want & have)
            totals[field][1] += len(want - have)
            totals[field][2] += len(have - want)
            if want != have:
                print(f"  {field}: missed {sorted(want - have)} extra {sorted(have - want)}")
    print("\nfield                      found  missed  extra")
    for field, (hit, missed, extra) in totals.items():
        print(f"{field:<26} {hit:>5} {missed:>7} {extra:>6}")
    if times:
        times.sort()
        print(f"\n{len(times)} resumes, median {times[len(times) // 2]:.0f} ms, max {times[-1]:.0f} ms")


def main():
    p = argparse.ArgumentParser(description="Resume text parser")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="compile the sources in config.toml into the index")
    pp = sub.add_parser("parse", help="parse one resume text file (or - for stdin) and print JSON")
    pp.add_argument("file")
    pe = sub.add_parser("eval", help="compare parse output with NAME.json next to each NAME.txt in DIR")
    pe.add_argument("dir")
    for sp in (pp, pe):
        sp.add_argument(
            "--today", type=date.fromisoformat, default=date.today(), help="date used for 'Present' (default: today)"
        )
    args = p.parse_args()
    if args.cmd == "build":
        from . import build

        build.build(CONFIG)
    elif args.cmd == "parse":
        cmd_parse(args)
    else:
        cmd_eval(args)


if __name__ == "__main__":
    main()
