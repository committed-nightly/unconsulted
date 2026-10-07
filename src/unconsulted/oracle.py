"""Everything this tool knows, it asks git for.

No config parsing happens here beyond splitting up git's own output. The point
of going through `git config --list` rather than reading the files is that git
has already done the hard parts -- scope order, includes, conditional includes,
quoting, line continuations -- and it cannot disagree with itself.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass


class GitUnavailable(RuntimeError):
    """No usable `git` on PATH."""


class GitFailed(RuntimeError):
    """git ran and said no."""


@dataclass(frozen=True)
class Entry:
    """One line of `git config --list --show-origin --show-scope`.

    `key` is as git prints it: section and variable lowercased, subsection
    left exactly as written. `order` is the position in git's output, which is
    precedence order -- for a single-valued read the highest `order` wins.
    """

    scope: str
    origin: str
    key: str
    value: str | None
    order: int

    @property
    def file(self) -> str | None:
        """The config file this came from, or None for non-file origins."""
        return self.origin[5:] if self.origin.startswith("file:") else None

    @property
    def section(self) -> str:
        return self.key.split(".", 1)[0]

    @property
    def variable(self) -> str:
        return self.key.rsplit(".", 1)[-1]

    @property
    def subsection(self) -> str | None:
        """The bit between section and variable, or None if there isn't one."""
        parts = self.key.split(".")
        return ".".join(parts[1:-1]) if len(parts) > 2 else None


def _run(args: list[str], cwd: str | None = None) -> str:
    if not shutil.which("git"):
        raise GitUnavailable("no `git` on PATH; this tool is a front end for it")
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            # LC_ALL so that any message we end up quoting is the English one.
            env={**os.environ, "LC_ALL": "C", "GIT_PAGER": "cat"},
        )
    except OSError as exc:  # pragma: no cover - needs a broken PATH entry
        raise GitUnavailable(str(exc)) from exc
    if proc.returncode != 0:
        raise GitFailed(f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout


def config_entries(cwd: str | None = None) -> list[Entry]:
    """Every config entry git would consult here, in precedence order.

    `-z` rather than the line-oriented form: a config value is allowed to
    contain a newline, and the readable output gives you no way to tell that
    from the start of the next entry.
    """
    raw = _run(["config", "--list", "-z", "--show-origin", "--show-scope"], cwd=cwd)
    return parse_z(raw)


def parse_z(raw: str) -> list[Entry]:
    """Turn `--list -z --show-origin --show-scope` output into entries.

    git emits three NUL-terminated fields per entry: scope, origin, and
    "key\\nvalue". A key present with no `=` at all has no newline and no
    value -- git treats that as an implicit true, which is not the same thing
    as the empty string, so it is kept distinct here.
    """
    fields = raw.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    out: list[Entry] = []
    for i in range(0, len(fields) - 2, 3):
        key, sep, value = fields[i + 2].partition("\n")
        out.append(
            Entry(
                scope=fields[i],
                origin=fields[i + 1],
                key=key,
                value=value if sep else None,
                order=len(out),
            )
        )
    return out


# `git help --config` ends with a prose line, and has for years. Anything
# without a dot in it is not a config key, which covers that line and any
# future friend of it.
_KEY_LINE = re.compile(r"^[A-Za-z][A-Za-z0-9]*\.[^\s]*$")


def known_config_keys(cwd: str | None = None) -> list[str]:
    """Every config key this git understands, as git lists them.

    Entries contain placeholders: `branch.<name>.remote`, `alias.*`,
    `credential.<url>.*`.
    """
    return [
        line for line in _run(["help", "--config"], cwd=cwd).splitlines() if _KEY_LINE.match(line)
    ]


def git_commands(cwd: str | None = None) -> dict[str, str]:
    """Every name that resolves to a git command here, and how.

    Three sources, because all three beat an alias:
      builtins  compiled into git
      main      everything in `git --exec-path`, including the non-builtins
      others    git-* found on PATH outside the exec path, e.g. git-lfs

    This is machine-specific on purpose. `git lfs` is a real command on a box
    with git-lfs installed and nothing at all on a box without it, and an
    alias named `lfs` is dead on the first and fine on the second.
    """
    kinds: dict[str, str] = {}
    for listing, kind in (("others", "a git-* on your PATH"), ("main", "shipped with git")):
        for name in _run([f"--list-cmds={listing}"], cwd=cwd).split():
            kinds[name] = kind
    for name in _run(["--list-cmds=builtins"], cwd=cwd).split():
        kinds[name] = "built into git"
    return kinds


def in_repo(cwd: str | None = None) -> bool:
    try:
        return _run(["rev-parse", "--is-inside-work-tree"], cwd=cwd).strip() == "true"
    except GitFailed:
        return False


def repo_root(cwd: str | None = None) -> str | None:
    try:
        return _run(["rev-parse", "--show-toplevel"], cwd=cwd).strip() or None
    except GitFailed:
        return None


def local_branches(cwd: str | None = None) -> list[str]:
    out = _run(["for-each-ref", "--format=%(refname:short)", "refs/heads/"], cwd=cwd)
    return out.split("\n") if out.strip() else []


def current_branch(cwd: str | None = None) -> str | None:
    """The checked-out branch, or None when detached or unborn."""
    try:
        return _run(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=cwd).strip() or None
    except GitFailed:
        return None


def remotes(cwd: str | None = None) -> list[str]:
    out = _run(["remote"], cwd=cwd)
    return out.split("\n") if out.strip() else []
