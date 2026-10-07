"""The checks.

Every verdict here traces back to something git said: the entry list, the key
list, the command list, the branch list, the remote list. Where a check needs
a judgement git will not make -- whether a repeated key is repeated on
purpose -- the judgement is in multivalue.py and says so out loud.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from . import multivalue, oracle
from .known import KeyIndex
from .locate import Lines

# Sections whose subsection is a URL that git normalises itself before
# comparing. Two spellings there are not two different things, so the
# case-split check stays out of them.
_URL_SECTIONS = {"credential", "http"}

# A value in branch.<name>.remote may name a remote, or be "." for this
# repository, or be a URL. Only the first can be checked against `git remote`.
_URLISH = re.compile(r"://|^[^/]+@[^/:]+:")

_REMOTE_NAMING_KEYS = {"remote", "pushremote"}


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    key: str
    scope: str
    file: str | None = None
    line: int | None = None
    detail: tuple[str, ...] = ()

    @property
    def where(self) -> str:
        if self.file is None:
            return "<not a file>"
        return f"{self.file}:{self.line}" if self.line else self.file


@dataclass
class Options:
    include_undocumented: bool = False
    multi_valued: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()


@dataclass
class Analysis:
    findings: list[Finding] = field(default_factory=list)
    entries: list[oracle.Entry] = field(default_factory=list)
    in_repo: bool = False
    skipped: list[str] = field(default_factory=list)


def analyse(cwd: str | None = None, options: Options | None = None) -> Analysis:
    opts = options or Options()
    entries = oracle.config_entries(cwd=cwd)
    index = KeyIndex(oracle.known_config_keys(cwd=cwd))
    inside = oracle.in_repo(cwd=cwd)
    base = cwd or os.getcwd()
    lines = Lines(base)
    result = Analysis(entries=entries, in_repo=inside)

    # Which occurrence of its key, within its own file, each entry is. The
    # locator needs this to pick the right line out of several.
    occurrence: dict[int, int] = {}
    per_file: dict[tuple[str | None, str], int] = defaultdict(int)
    for e in entries:
        seen = per_file[(e.file, e.key)]
        occurrence[e.order] = seen
        per_file[(e.file, e.key)] = seen + 1

    def locate(e: oracle.Entry) -> int | None:
        if e.file is None:
            return None
        total = per_file[(e.file, e.key)]
        return lines.resolve(e.file, e.key, occurrence[e.order], total)

    def at(e: oracle.Entry, code: str, message: str, *detail: str) -> Finding:
        return Finding(
            code=code,
            message=message,
            key=e.key,
            scope=e.scope,
            file=e.file,
            line=locate(e),
            detail=tuple(detail),
        )

    found: list[Finding] = []
    found += _shadowed(entries, opts, locate, at)
    found += _unknown_keys(entries, index, opts, at)
    found += _dead_aliases(entries, cwd, at)
    found += _includes(entries, base, at)
    if inside:
        found += _branch_checks(entries, cwd, at, result)
    else:
        result.skipped.append("not in a git repository: skipped the branch and remote checks")
    found += _case_split(entries, at)

    if opts.scopes:
        found = [f for f in found if f.scope in opts.scopes]

    result.findings = sorted(found, key=lambda f: (f.file or "", f.line or 0, f.code))
    return result


def _shadowed(entries, opts, locate, at) -> list[Finding]:
    """Values a later line always beats.

    git lists entries in precedence order, so for a key read as a single value
    -- `git config user.email`, and almost everything inside git -- only the
    last one can ever be returned. The earlier ones are read, parsed, and
    thrown away.
    """
    by_key: dict[str, list[oracle.Entry]] = defaultdict(list)
    for e in entries:
        by_key[e.key].append(e)

    out = []
    for key, group in by_key.items():
        if len(group) < 2 or multivalue.reason(key, opts.multi_valued):
            continue
        winner = group[-1]
        win_line = locate(winner)
        win_at = f"{winner.file}:{win_line}" if win_line else (winner.file or winner.origin)
        for loser in group[:-1]:
            same = loser.value == winner.value
            out.append(
                at(
                    loser,
                    "shadowed",
                    f"{key} never applies; {win_at} sets it again"
                    + (" to the same value" if same else f" to {winner.value!r}"),
                    f"git config {key} returns {winner.value!r}, from {winner.scope} scope.",
                    "Delete this line, or move it after the one that wins."
                    if not same
                    else "Both lines say the same thing; delete either.",
                )
            )
    return out


def _unknown_keys(entries, index: KeyIndex, opts, at) -> list[Finding]:
    """Keys that are not in git's documented list.

    git accepts any `section.key` you write and never validates a name,
    because it only ever looks up the names it wants. So `core.autocrfl` sits
    in your config forever, costing you CRLF handling, and nothing says a
    word.

    The trap is that `git help --config` is not a complete list of the keys
    git reads. It is generated from Documentation/config/, and some keys are
    documented elsewhere -- `filter.<driver>.process` and
    `filter.<driver>.required` live in gitattributes(5) and are absent from
    it, as is `submodule.<name>.path`. Any check that said "not in the list,
    therefore dead" would call those three dead, and they are not.

    So the default finding needs stronger evidence than absence: a documented
    key in the same section, the same shape, within one or two characters.
    `core.autocrfl` has one of those and `filter.lfs.process` does not, which
    is the distinction that matters. Everything else is behind
    --include-undocumented, where the name says only what we know.
    """
    out = []
    seen: set[str] = set()
    for e in entries:
        if e.key in seen or index.knows_key(e.key):
            continue
        seen.add(e.key)
        own_section = index.knows_section(e.section)
        hint = index.suggest(e.key) if own_section else None
        if hint:
            out.append(
                at(
                    e,
                    "typo-key",
                    f"{e.key} is not a key git documents; did you mean {hint}?",
                    f"Nothing reads {e.key}. git validates no key names, so this line "
                    "has no effect and raises no error.",
                )
            )
        elif opts.include_undocumented:
            where = (
                f"`{e.section}` is one of git's own sections"
                if own_section
                else f"git has no `{e.section}` section"
            )
            out.append(
                at(
                    e,
                    "undocumented-key",
                    f"{e.key} is not in `git help --config`",
                    f"{where}. That list is incomplete, and other tools keep their "
                    "settings here too, so this may well be read by something.",
                )
            )
    return out


def _alias_name(key: str) -> str | None:
    """The command name an `alias.*` entry defines, or None."""
    parts = key.split(".")
    if parts[0] != "alias" or len(parts) < 2:
        return None
    # git 2.50 added `alias.<name>.command` alongside `alias.<name>`.
    if len(parts) == 3 and parts[2] == "command":
        return parts[1]
    return ".".join(parts[1:]) if len(parts) == 2 else None


def _dead_aliases(entries, cwd, at) -> list[Finding]:
    """Aliases that lose to a real command.

    git resolves a name against its builtins, then against the commands in
    its exec path, then against `git-<name>` on your PATH, and only then
    against your aliases. So an alias can never shadow any of those three --
    and the surprising member of that list is the third. On a box with
    git-lfs installed, `alias.lfs` is dead; on a box without, it works. Which
    is why this asks the git in front of it rather than carrying a list.
    """
    commands = oracle.git_commands(cwd=cwd)
    out = []
    for e in entries:
        name = _alias_name(e.key)
        if name is None or name not in commands:
            continue
        out.append(
            at(
                e,
                "dead-alias",
                f"alias `{name}` never runs; `git {name}` is already a command "
                f"({commands[name]})",
                "git looks up builtins, then its exec path, then git-* on PATH, "
                "then aliases. Yours is last.",
                f"Rename the alias. `git {name}` will keep doing what it does now.",
            )
        )
    return out


def _expand(path: str, relative_to: str | None) -> str:
    path = os.path.expanduser(path)
    if not os.path.isabs(path) and relative_to:
        path = os.path.join(os.path.dirname(relative_to), path)
    return path


def _gitdir_prefix(condition: str) -> str | None:
    """The literal directory a `gitdir:` condition requires, if any.

    Returns None when the condition is not one we can check: a pattern git
    will implicitly prefix with `**/` matches anywhere, so there is no
    directory it needs.
    """
    kind, _, pattern = condition.partition(":")
    if kind.lower() not in {"gitdir", "gitdir/i"}:
        return None
    if not pattern.startswith(("~/", "/", "./")):
        return None  # git prepends **/ -- could match anywhere
    literal = re.split(r"[*?\[]", pattern, maxsplit=1)[0]
    return os.path.expanduser(literal) or None


def _includes(entries, base, at) -> list[Finding]:
    """Includes that load nothing.

    A missing include is git's quietest failure: there is no warning, no
    non-zero exit, and no trace in `git config --list`. The file simply is
    not there and every setting you believed was in it is absent.
    """
    def absolute(path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(base, path)

    loaded = {os.path.realpath(absolute(e.file)) for e in entries if e.file}

    out = []
    for e in entries:
        parts = e.key.split(".")
        if parts[0] not in {"include", "includeif"} or parts[-1] != "path":
            continue
        conditional = parts[0] == "includeif"
        condition = ".".join(parts[1:-1]) if conditional else None
        target = _expand(e.value or "", absolute(e.file) if e.file else None)

        if not os.path.isfile(target):
            out.append(
                at(
                    e,
                    "include-missing",
                    f"include of {e.value!r} loads nothing; {target} is not a file",
                    "git ignores a missing include silently -- no warning, no error.",
                    "Fix the path, or delete the include.",
                )
            )
            continue

        if conditional:
            needed = _gitdir_prefix(condition or "")
            if needed and not os.path.isdir(needed):
                out.append(
                    at(
                        e,
                        "includeif-no-such-dir",
                        f"condition `{condition}` can never match; {needed} is not a "
                        "directory on this machine",
                        "A gitdir: condition only matches repositories under that path.",
                        "Check the path for a typo. Nothing under it exists to match.",
                    )
                )
            continue

        # Unconditional and present, so git read it. If it contributed no
        # entry, there was nothing in it to contribute.
        if os.path.realpath(target) not in loaded:
            out.append(
                at(
                    e,
                    "include-empty",
                    f"include of {e.value!r} sets nothing; the file has no config in it",
                    "git read the file. It contained no variables, only blank lines "
                    "or comments.",
                )
            )
    return out


def _branch_checks(entries, cwd, at, result: Analysis) -> list[Finding]:
    """Branch sections for branches that are gone, and remotes that are not there."""
    branches = set(oracle.local_branches(cwd=cwd))
    remotes = set(oracle.remotes(cwd=cwd))
    out = []

    if not branches:
        result.skipped.append(
            "repository has no branches yet: skipped the stale-branch check"
        )

    seen: set[str] = set()
    for e in entries:
        if e.section != "branch" or e.subsection is None:
            continue
        name = e.subsection
        if branches and name not in branches and name not in seen:
            seen.add(name)
            out.append(
                at(
                    e,
                    "stale-branch",
                    f"[branch \"{name}\"] has no branch; nothing here is consulted",
                    "git only reads a branch section while that branch is checked out "
                    "or named.",
                    "Harmless until the branch comes back, which is also the catch.",
                )
            )
        if e.variable in _REMOTE_NAMING_KEYS and e.value:
            value = e.value
            if value != "." and not _URLISH.search(value) and value not in remotes:
                out.append(
                    at(
                        e,
                        "no-such-remote",
                        f"{e.key} names remote {value!r}, which this repository "
                        "does not have",
                        f"Remotes here: {', '.join(sorted(remotes)) or 'none'}.",
                    )
                )
    return out


def _case_split(entries, at) -> list[Finding]:
    """Subsections that differ only in case, and so are not the same thing.

    Section and variable names fold to lower case in git. Quoted subsection
    names do not. `[remote "Origin"]` and `[remote "origin"]` are two remotes
    with two sets of settings, and `git remote` will show you both, which is
    the only warning you get.
    """
    groups: dict[tuple[str, str], dict[str, oracle.Entry]] = defaultdict(dict)
    for e in entries:
        if e.subsection is None or e.section in _URL_SECTIONS:
            continue
        groups[(e.section, e.subsection.lower())].setdefault(e.subsection, e)

    out = []
    for (section, _), spellings in groups.items():
        if len(spellings) < 2:
            continue
        names = ", ".join(f'"{s}"' for s in sorted(spellings))
        for spelling, entry in sorted(spellings.items()):
            out.append(
                at(
                    entry,
                    "case-split",
                    f"[{section} \"{spelling}\"] is one of {len(spellings)} sections "
                    f"differing only in case: {names}",
                    "Subsection names are case sensitive when quoted, so these are "
                    "separate settings, not one.",
                    "Pick a spelling and merge them.",
                )
            )
    return out
