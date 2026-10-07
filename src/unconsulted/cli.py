"""Command line.

Exit codes:
  0  nothing to report
  1  findings (or, for `explain`, the key is not set anywhere)
  2  could not run: no git, a bad directory, a usage mistake
"""

from __future__ import annotations

import argparse
import os
import sys

from . import oracle, report
from .analyse import Options, analyse
from .locate import Lines
from .multivalue import MULTI_VALUED

_SCOPES = ("system", "global", "local", "worktree", "command")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="unconsulted",
        description="Find the lines in your git config that git never consults.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="report every unconsulted line")
    check.add_argument("-C", dest="directory", metavar="DIR", help="run as if in DIR")
    check.add_argument("-q", "--quiet", action="store_true", help="one line per finding")
    check.add_argument(
        "--scope",
        action="append",
        choices=_SCOPES,
        dest="scopes",
        help="only report findings in this scope; repeatable",
    )
    check.add_argument(
        "--include-undocumented",
        action="store_true",
        help="also report every key missing from `git help --config`. Off by "
        "default: that list is incomplete, and other tools store settings in "
        "git config on purpose",
    )
    check.add_argument(
        "--multi-valued",
        action="append",
        metavar="KEY",
        dest="multi_valued",
        help="treat KEY as legitimately repeated, so do not call it shadowed; "
        "accepts <placeholder> as in remote.<name>.fetch. Repeatable.",
    )

    exp = sub.add_parser("explain", help="show every value of one key and which wins")
    exp.add_argument("key", help="a config key, e.g. user.email")
    exp.add_argument("-C", dest="directory", metavar="DIR", help="run as if in DIR")

    sub.add_parser("multi-valued", help="print the keys we treat as legitimately repeated")

    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.command == "multi-valued":
        print("Keys where a repeat is the point, not a mistake.")
        print("`shadowed` stays quiet about these. Add your own with --multi-valued.")
        print()
        for key, why in sorted(MULTI_VALUED.items(), key=lambda kv: kv[0].lower()):
            print(f"  {key:40} {why}")
        return 0

    try:
        if args.command == "check":
            return _check(args)
        return _explain(args)
    except oracle.GitUnavailable as exc:
        print(f"unconsulted: {exc}", file=sys.stderr)
        return 2
    except oracle.GitFailed as exc:
        print(f"unconsulted: {exc}", file=sys.stderr)
        return 2


def _check(args) -> int:
    result = analyse(
        cwd=args.directory,
        options=Options(
            include_undocumented=args.include_undocumented,
            multi_valued=tuple(args.multi_valued or ()),
            scopes=tuple(args.scopes or ()),
        ),
    )
    if args.quiet:
        report.terse(result.findings)
    else:
        report.verbose(result)
    return 1 if result.findings else 0


def _explain(args) -> int:
    entries = oracle.config_entries(cwd=args.directory)
    base = args.directory or os.getcwd()
    found = report.explain(args.key, entries, Lines(base))
    return 0 if found else 1
