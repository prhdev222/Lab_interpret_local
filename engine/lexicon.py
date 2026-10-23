"""Loads the editable dictionary (data/lexicon.json) and compiles the regular expressions built from it."""
from __future__ import annotations

import json
import os
import re

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Letters that must not touch a parameter name ("cr" inside "crp", "hb" inside "hba1c" is handled by alias length order).
_WORD = "A-Za-z0-9ก-๙"
NUM = r"\d+(?:\.\d+)?"
ARROW = r"\s*(?:-{1,3}>|=+>)\s*"          # input is normalised first: → ⇒ ➔ become '->'


def _alias_regex(alias: str) -> str:
    return re.escape(alias.strip().lower()).replace(r"\ ", r"\s*")


class Lexicon:
    def __init__(self, data: dict):
        self.data = data
        self.two_digit_year_is_be = bool(data.get("settings", {}).get("two_digit_year_is_buddhist_era", True))
        self.negations = sorted(data["negation_prefixes"], key=len, reverse=True)
        self.concepts = data["concepts"]
        self.smoking = data["smoking"]
        self.params = data["params"]

        # problem alias -> canonical name
        self.problem_alias = {}
        for canon, aliases in data["problems"].items():
            self.problem_alias[canon.lower()] = canon
            for a in aliases:
                self.problem_alias[a.lower()] = canon

        # param alias -> canonical param
        self.param_alias = {}
        for canon, spec in self.params.items():
            for a in spec["aliases"] + [canon]:
                self.param_alias[re.sub(r"\s+", "", a.lower())] = canon

        self.range_params = {c for c, spec in self.params.items() if spec.get("kind") == "range"}
        plain = {c: spec for c, spec in self.params.items() if c not in self.range_params}
        names = sorted({a for spec in plain.values() for a in spec["aliases"]} | set(plain), key=len, reverse=True)
        name_re = "|".join(_alias_regex(n) for n in names)
        units = sorted({re.escape(u) for u in data["units"]} | {re.escape(u.replace("u", "µ", 1)) for u in data["units"] if "umol" in u}, key=len, reverse=True)
        self.unit_re = "(?:" + "|".join(units) + ")"
        elem = rf"(?:{NUM}/{NUM}|{NUM})(?:\s*{self.unit_re})?"
        series = rf"{elem}(?:{ARROW}{elem})*"
        self.token_re = re.compile(
            rf"(?<![{_WORD}])(?P<name>{name_re})(?![A-Za-zก-๙])\s*[:=]?\s*(?P<series>{series})",
            re.IGNORECASE,
        )
        range_names = sorted({a for c in self.range_params for a in self.params[c]["aliases"]}, key=len, reverse=True)
        self.range_re = re.compile(
            rf"(?<![{_WORD}])(?P<name>{'|'.join(_alias_regex(n) for n in range_names)})(?![A-Za-zก-๙])\s*[:=]?\s*"
            rf"(?P<lo>{NUM})\s*(?:-|–|—|ถึง|to)\s*(?P<hi>{NUM})", re.IGNORECASE) if range_names else None
        self.elem_re = re.compile(rf"(?P<a>{NUM})(?:/(?P<b>{NUM}))?\s*(?P<u>{self.unit_re})?\s*$", re.IGNORECASE)
        self.arrow_re = re.compile(ARROW)
        fw = sorted({w.strip().lower() for w in data.get("filler_words", []) if w.strip()}, key=len, reverse=True)
        self.filler_re = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in fw) + r")(?![a-z0-9])", re.IGNORECASE) if fw else None
        self.tags = {tid: self._compile_tag(spec) for tid, spec in data.get("tags", {}).items() if isinstance(spec, dict)}


    @staticmethod
    def _compile_tag(spec: dict) -> list[re.Pattern]:
        """One pattern per phrase/regex, so that the longest hit wins even when a shorter phrase starts earlier."""
        out = []
        for ph in spec.get("phrases", []):
            ph = ph.strip().lower()
            if not ph:
                continue
            lead = r"(?<![a-z0-9])" if ph[0].isascii() and ph[0].isalnum() else ""
            trail = r"(?![a-z0-9])" if ph[-1].isascii() and ph[-1].isalnum() and len(ph) <= 3 else ""
            out.append(re.compile(lead + re.escape(ph).replace("\\ ", r"\s+") + trail, re.IGNORECASE))
        out += [re.compile(r, re.IGNORECASE) for r in spec.get("regex", []) if r]
        return out


_cache: dict[str, Lexicon] = {}


def load_lexicon(path: str | None = None) -> Lexicon:
    path = path or os.path.join(DATA_DIR, "lexicon.json")
    mtime = os.path.getmtime(path)
    key = f"{path}:{mtime}"
    if key not in _cache:
        with open(path, encoding="utf-8") as f:
            _cache.clear()
            _cache[key] = Lexicon(json.load(f))
    return _cache[key]
