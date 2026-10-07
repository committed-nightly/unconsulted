"""Is this a key git has heard of?

The list comes from `git help --config`, which the local git generates from
its own documentation, so it is exactly as current as the git you are running.

Matching errs generously on purpose. The finding this feeds is "git has never
heard of this", and a wrong one of those sends somebody to delete a line that
was doing its job. A placeholder therefore matches anything at all, including
dots -- `credential.<url>.*` has to cover
`credential.https://github.com.helper`, where the URL contains a dot and a
colon and a slash.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


def _to_regex(pattern: str) -> re.Pattern[str]:
    """`branch.<name>.remote` -> a regex; `<name>` and `*` match anything."""
    out = []
    for part in re.split(r"(<[^>]+>|\*)", pattern):
        out.append(".+" if part.startswith("<") or part == "*" else re.escape(part))
    return re.compile("".join(out) + r"\Z", re.IGNORECASE)


@dataclass
class KeyIndex:
    """git's own key list, indexed for the two questions we ask of it."""

    patterns: list[str]

    def __post_init__(self) -> None:
        self._exact = {p.lower() for p in self.patterns if "<" not in p and "*" not in p}
        self._wild = [_to_regex(p) for p in self.patterns if "<" in p or "*" in p]
        # Section names are case-insensitive in git, so compare them folded.
        self._sections = {p.split(".", 1)[0].lower() for p in self.patterns}

    def knows_key(self, key: str) -> bool:
        if key.lower() in self._exact:
            return True
        return any(w.match(key) for w in self._wild)

    def knows_section(self, section: str) -> bool:
        return section.lower() in self._sections

    def suggest(self, key: str) -> str | None:
        """The known key this one looks like a typo of, if any.

        Only ever suggests within the same section, and only among keys with
        the same shape -- suggesting `branch.<name>.remote` for `branch.remot`
        would be noise, because the fix is not to rename the variable.
        """
        parts = key.split(".")
        section = parts[0].lower()
        candidates = [
            p
            for p in self.patterns
            if p.split(".", 1)[0].lower() == section
            and "<" not in p
            and "*" not in p
            and len(p.split(".")) == len(parts)
        ]
        # 0.8 is tight enough that only genuine near-misses survive: it takes
        # `core.autocrfl` -> `core.autocrlf` and leaves `core.wibble` alone.
        hits = difflib.get_close_matches(key.lower(), [c.lower() for c in candidates], n=1, cutoff=0.8)
        if not hits:
            return None
        # Give the suggestion back in git's documented spelling, not folded.
        return next(c for c in candidates if c.lower() == hits[0])
