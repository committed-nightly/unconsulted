"""Output. Terse by default, because this is a thing you run and read."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable

from .analyse import Analysis, Finding
from .oracle import Entry


def _shorten(path: str | None) -> str:
    if not path:
        return "<not a file>"
    home = os.path.expanduser("~")
    if home and path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def terse(findings: Iterable[Finding], out=None) -> None:
    """One line each: where, what, why. The form `grep` and an editor want."""
    out = out or sys.stdout
    for f in findings:
        place = _shorten(f.file)
        if f.line:
            place = f"{place}:{f.line}"
        print(f"{place}: {f.code}: {f.message}", file=out)


def verbose(analysis: Analysis, out=None) -> None:
    out = out or sys.stdout
    for note in analysis.skipped:
        print(f"note: {note}", file=out)
    if analysis.skipped:
        print(file=out)

    for f in analysis.findings:
        place = _shorten(f.file)
        if f.line:
            place = f"{place}:{f.line}"
        print(f"{place}", file=out)
        print(f"  {f.code}: {f.message}", file=out)
        for line in f.detail:
            print(f"      {line}", file=out)
        print(file=out)

    n = len(analysis.findings)
    if n:
        print(f"{n} line{'s' if n != 1 else ''} git does not consult.", file=out)
    else:
        print("Nothing unconsulted. Every line in your git config is read.", file=out)


def explain(key: str, entries: list[Entry], lines, out=None) -> bool:
    """Show every assignment of one key, in git's order, and which one wins.

    Returns whether the key was set at all.
    """
    out = out or sys.stdout
    matches = [e for e in entries if e.key.lower() == key.lower()]
    if not matches:
        print(f"{key} is not set anywhere git looks.", file=out)
        return False

    print(f"{matches[-1].key}   every value git read, in the order it read them", file=out)
    print(file=out)
    width = max(len(e.scope) for e in matches)
    for i, e in enumerate(matches):
        last = i == len(matches) - 1
        mark = "->" if last else "  "
        place = _shorten(e.file) or e.origin
        if e.file:
            total = sum(1 for o in matches if o.file == e.file)
            seen = sum(1 for o in matches[:i] if o.file == e.file)
            if (ln := lines.resolve(e.file, e.key, seen, total)) is not None:
                place = f"{place}:{ln}"
        shown = "(set, no value: git reads this as true)" if e.value is None else repr(e.value)
        print(f"  {mark} {e.scope:<{width}}  {shown}", file=out)
        print(f"     {' ' * width}  {place}", file=out)
    print(file=out)
    print(
        f"`git config {matches[-1].key}` returns the arrowed value. "
        f"{'No other value is read.' if len(matches) == 1 else 'Earlier ones are read and discarded, unless the key is multi-valued.'}",
        file=out,
    )
    return True
