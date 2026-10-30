"""Resume text parser built on rules, reference data and a small spaCy model (no LLM)."""

import os
import tomllib
from datetime import date

from .match import IndexOutOfDateError, load_index
from .parse import InputTooLargeError, ModelNotInstalledError, nlp
from .parse import parse as parse_resume

__all__ = ["IndexOutOfDateError", "InputTooLargeError", "ModelNotInstalledError", "Parser", "parse"]

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.toml")


class Parser:
    """Loads the index, config and spaCy model once; each parse() then takes milliseconds."""

    def __init__(self):
        with open(CONFIG, "rb") as f:
            raw = f.read().decode()
        self.cfg = tomllib.loads(raw)
        self.index = load_index(
            os.path.join(HERE, self.cfg["index"]), raw, os.path.join(HERE, self.cfg["vocab"]["dir"])
        )
        nlp()

    def parse(self, text, today=None):
        """Resume text -> dict of fields; `today` (default: date.today()) is the date used for 'Present'."""
        return parse_resume(text, self.index, self.cfg, today or date.today())


_default = None


# Rebinds the name taken by the parse submodule; inside the package, import from it with `from .parse import ...`.
def parse(text, today=None):
    """Parse with a shared Parser, created on the first call."""
    global _default
    if _default is None:
        _default = Parser()
    return _default.parse(text, today)
