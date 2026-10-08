#!/usr/bin/env python3
"""Re-derive the multi-valued key candidates from git's own man page.

There is no `git config` query for "is this key multi-valued", so
src/unconsulted/multivalue.py carries a table. This script is where that table
comes from, so it can be audited rather than believed:

    python3 tools/regen_multivalue.py

It prints candidates and the phrase that identified each. It is a *seed*, not
the table. The extractor over-matches (`core.deltaBaseCacheLimit` says
"multiple times" about delta bases, not about itself) and under-matches (the
man page says "a repeated field" in one place and "String(s)" in another), so
every candidate was read in context before going into the table, and several
entries were added by hand. The comments in multivalue.py record which.

Needs man(1) and git's man pages installed, which rules out most CI runners.
"""

from __future__ import annotations

import re
import subprocess
import sys

# Terms in git-config(5) sit at seven spaces of indent, bodies deeper.
TERM = re.compile(r"^ {7}(?! )(?P<key>[A-Za-z][A-Za-z0-9]*\.[A-Za-z0-9<>*.:/_-]*[A-Za-z0-9>*])$")

PHRASE = re.compile(
    r"multi-valued|multiple times|may be repeated|appear multiple|given multiple|"
    r"specified multiple|more than once|specify the key more|repeated field|"
    r"more than one definition|may be defined|may be set multiple|"
    r"this is a list|is a string list|String\(s\)|set of \"refspec\"|"
    r"add more than one",
    re.IGNORECASE,
)


def man_page() -> str:
    proc = subprocess.run(
        ["man", "git-config"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "MANWIDTH": "100"},
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit("no git-config(5) on this machine: " + proc.stderr.strip())
    return proc.stdout


def candidates(text: str) -> dict[str, str]:
    lines = text.splitlines()
    terms = [(i, m.group("key")) for i, line in enumerate(lines) if (m := TERM.match(line))]
    out: dict[str, str] = {}
    for n, (start, key) in enumerate(terms):
        end = terms[n + 1][0] if n + 1 < len(terms) else len(lines)
        body = " ".join(line.strip() for line in lines[start + 1 : end])
        if match := PHRASE.search(body):
            out[key] = match.group(0)
    return out


def main() -> int:
    found = candidates(man_page())
    version = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    print(f"# candidates from git-config(5), {version}")
    print("# Read each in context before trusting it; see the module docstring.")
    for key, phrase in sorted(found.items(), key=lambda kv: kv[0].lower()):
        print(f'    "{key}": \'man: "{phrase.lower()}"\',')
    print(f"# {len(found)} candidates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
