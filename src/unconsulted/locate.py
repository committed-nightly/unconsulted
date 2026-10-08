"""Find the line a config entry was written on, for display only.

git tells us which *file* an entry came from and never which line, so this is
the one place the tool looks at config syntax itself. That makes it the one
place it could be wrong, so it is fenced in two ways:

  1. Nothing here decides anything. A finding is a finding whether or not we
     found its line; a missing line number costs you a column of output.

  2. It checks its own work. For each file we know how many values git read
     for a key; if the scan does not find the same number, we report no line
     numbers for that key rather than guessing which one you meant.

The second rule is what makes this safe to ship. Config syntax has corners --
`[section "sub"]` against `[section.sub]`, a key on the same line as its
section header, values continued over a line break, `#` and `;` comments --
and the honest response to a corner we got wrong is to go quiet, not to point
at line 12 with confidence.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict

_SECTION = re.compile(r'^\s*\[\s*(?P<name>[A-Za-z0-9.-]+)\s*(?:"(?P<sub>.*)")?\s*\]')
_VARIABLE = re.compile(r"^\s*(?P<name>[A-Za-z][A-Za-z0-9-]*)\s*(?:$|[=\s;#])")


def _normalise(section: str, sub: str | None, variable: str) -> str:
    """Spell a key the way `git config --list` spells it.

    Section and variable fold to lower case. A quoted subsection keeps its
    case; the dotted `[section.Sub]` form does not, because git lowercases
    that one -- which is why `[remote.Origin]` and `[remote.origin]` are the
    same remote while `[remote "Origin"]` and `[remote "origin"]` are two.
    """
    if sub is None:
        head, _, dotted = section.partition(".")
        return f"{head.lower()}.{dotted.lower()}.{variable.lower()}" if dotted else f"{head.lower()}.{variable.lower()}"
    return f"{section.lower()}.{sub}.{variable.lower()}"


def scan(text: str) -> dict[str, list[int]]:
    """Map each key in a config file to the 1-based lines that assign it."""
    found: dict[str, list[int]] = defaultdict(list)
    section: str | None = None
    sub: str | None = None
    continuing = False

    for lineno, raw in enumerate(text.splitlines(), start=1):
        if continuing:
            # Inside a value continued from the previous line. It can only end
            # here or continue again; either way there is no key to find.
            continuing = raw.rstrip("\r").endswith("\\")
            continue

        line = raw
        if m := _SECTION.match(line):
            section, sub = m.group("name"), m.group("sub")
            line = line[m.end() :]  # a key may follow on the same line

        stripped = line.strip()
        if stripped and not stripped.startswith(("#", ";")):
            if (v := _VARIABLE.match(line)) and section is not None:
                found[_normalise(section, sub, v.group("name"))].append(lineno)

        # A backslash at end of line continues a value. Only meaningful if
        # this line had a value at all, but treating a trailing backslash as a
        # continuation unconditionally is the safer error: it can only make us
        # miss a key, and a missed key trips the count check and goes quiet.
        continuing = line.rstrip("\r").endswith("\\")

    return dict(found)


class Lines:
    """Line numbers for keys in config files, or nothing when unsure.

    `base` is the directory git ran in. git prints a local config's origin
    relative to its own working directory -- plain `.git/config` -- so with
    `-C somewhere` those paths mean nothing to a process that is still in the
    directory it started in. Resolving them against anything else is not a
    missing line number but a wrong one, read out of a different repository's
    config that happens to have the same relative path.
    """

    def __init__(self, base: str | None = None) -> None:
        self._files: dict[str, dict[str, list[int]]] = {}
        self._base = base

    def _resolve_path(self, path: str) -> str:
        if os.path.isabs(path) or not self._base:
            return path
        return os.path.join(self._base, path)

    def load(self, path: str) -> None:
        if path in self._files:
            return
        try:
            with open(self._resolve_path(path), encoding="utf-8", errors="replace") as fh:
                self._files[path] = scan(fh.read())
        except OSError:
            self._files[path] = {}

    def resolve(self, path: str, key: str, occurrence: int, expected: int) -> int | None:
        """Line of the `occurrence`-th (0-based) assignment of `key` in `path`.

        `expected` is how many values git read for this key from this file.
        Returns None unless the scan agrees with that count exactly.
        """
        self.load(path)
        lines = self._files.get(path, {}).get(key, [])
        if len(lines) != expected or not 0 <= occurrence < len(lines):
            return None
        return lines[occurrence]
