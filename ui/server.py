"""python ui/server.py [--port 8000]: browser UI for the parser at http://127.0.0.1:8000"""

import argparse
import functools
import json
import logging
import os
import sys
import time
import tomllib
from datetime import date
from http.server import HTTPServer, SimpleHTTPRequestHandler

UI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(UI))

import cli
import match
import parse

MAX_TEXT = 200_000
log = logging.getLogger("resulex.ui")


def section_spans(text, cfg):
    """Character spans of the sections parse.split_sections finds: [{name, start, end, header: [s, e] | None}]."""
    vocab = {match.norm(p): name for name, phrases in cfg["sections"].items() for p in phrases}
    words = {w for p in vocab for w in p.split()}
    out = [{"name": "top", "start": 0, "header": None}]
    pos = 0
    for chunk in text.splitlines(keepends=True):
        line = (chunk.splitlines() or [""])[0]
        if line.strip():
            name, _ = parse.header(line.strip(), vocab, words)
            if name:
                out.append({"name": name, "start": pos, "header": [pos, pos + len(line)]})
        pos += len(chunk)
    for sec, nxt in zip(out, out[1:] + [{"start": len(text)}]):
        sec["end"] = nxt["start"]
    return [s for s in out if s["end"] > s["start"] or s["name"] != "top"]


def make_handler(run, cfg):
    class Handler(SimpleHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/api/parse":
                return self.send_error(404)
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), MAX_TEXT * 4)))
                text, today = body.get("text"), body.get("today")
                if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
                    raise ValueError(f"text must be a non-empty string of at most {MAX_TEXT} characters")
                today = date.fromisoformat(today) if today else date.today()
            except (ValueError, TypeError, AttributeError) as e:
                return self.reply(400, {"error": str(e)})
            text = text.replace("\r", "")  # parse() does the same; offsets must match what it saw
            t = time.perf_counter()
            try:
                result = run(text, today)
            except Exception as e:  # report the parser failure to the page instead of dropping the connection
                log.exception("parse failed for %d chars", len(text))
                return self.reply(500, {"error": f"parser failed: {type(e).__name__}: {e}"})
            ms = (time.perf_counter() - t) * 1000
            self.reply(
                200,
                {
                    "text": text,
                    "sections": section_spans(text, cfg),
                    "result": result,
                    "ms": round(ms, 1),
                    "date_patterns": [parse.DATE_RANGE.pattern, parse.MONTH_DATE.pattern],
                },
            )

        def reply(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main():
    p = argparse.ArgumentParser(description="ResuLex browser UI")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with open(cli.CONFIG, "rb") as f:
        cfg = tomllib.load(f)
    log.info("loading index and spaCy model...")
    handler = functools.partial(make_handler(cli.load_parser(), cfg), directory=UI)
    # Localhost only and single-threaded: resumes are personal data, and one shared spaCy pipeline.
    server = HTTPServer(("127.0.0.1", args.port), handler)
    log.info("open http://127.0.0.1:%d", args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
