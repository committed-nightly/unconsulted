"""Keys where a second value is the point, not a mistake.

This table is the one thing in the tool that is asserted rather than asked.
Everywhere else, git answers the question. There is no `git config` query for
"is this key multi-valued" -- the knowledge lives in git's C, in whether a
setting is read with `git_config_get_string` or accumulated into a
`string_list`, and nothing exposes it.

So: `tools/regen_multivalue.py` extracts candidates from the git-config(5) man
page on the box, and the result was checked by hand against the surrounding
prose. Provenance for each entry is the phrase that identified it. Entries
with no phrase were added by hand after reading the paragraph; the reason is
in the comment.

Getting this wrong in one direction is much worse than the other. A key
missing from this table produces a `shadowed` finding that is wrong -- it
tells you a line is dead when git reads it happily. A key wrongly *in* the
table only means we stay quiet about it. So when in doubt, it goes in, and
`--multi-valued` lets you add your own without waiting for us.
"""

from __future__ import annotations

import re

# Extracted by tools/regen_multivalue.py from git-config(5), git 2.55.0.
MULTI_VALUED: dict[str, str] = {
    "blame.ignoreRevsFile": 'man: "may be repeated"',
    "core.gitProxy": 'man: "may be set multiple times"',
    "credential.helper": 'man: "multiple helpers may be defined"',
    "format.notes": 'man: "specified multiple times"',
    "hook.<friendly-name>.event": 'man: "this is a multi-valued key"',
    "merge.suppressDest": 'man: "this multi-valued"',
    "notes.displayRef": 'man: "specified more than once"',
    "pack.preferBitmapTips": 'man: "can be given multiple times"',
    "push.pushOption": 'man: "a multi-valued variable"',
    "receive.procReceiveRefs": 'man: "a multi-valued variable"',
    "remote.<name>.fetch": 'man: "the default set of refspec"',
    "remote.<name>.negotiationInclude": 'man: "multi-valued config option"',
    "remote.<name>.negotiationRestrict": 'man: "multi-valued config option"',
    "remote.<name>.push": 'man: "the default set of refspec"',
    "remote.<name>.serverOption": 'man: "a multi-valued variable"',
    "safe.directory": 'man: "a multi-valued setting"',
    "submodule.active": 'man: "a repeated field"',
    "transfer.hideRefs": 'man: "use more than one definition"',
    "versionsort.suffix": 'man: "if specified multiple times"',
    # Added by hand. The man page describes each of these as plural without
    # using a phrase the extractor looks for; the quoted bit is from its
    # paragraph.
    "remote.<name>.url": 'man: "a configured remote can have multiple URLs"',
    "remote.<name>.pushurl": 'man: "can have multiple push URLs"',
    "receive.hideRefs": 'man: "the same as transfer.hideRefs"',
    "uploadpack.hideRefs": 'man: "the same as transfer.hideRefs"',
    "credential.<url>.helper": "per-URL form of credential.helper",
    "url.<base>.insteadOf": "git accumulates these into a rewrite list",
    "url.<base>.pushInsteadOf": "git accumulates these into a rewrite list",
    "log.excludeDecoration": 'man: "the specified patterns", plural',
    # Not in the man page's variable list at all -- includes are documented in
    # their own section. Two include.path lines in one file both load, which
    # is easy to confirm and is what the repeated-include idiom relies on.
    "include.path": "every include.path in a file is read",
    "includeIf.<condition>.path": "every includeIf that matches is read",
}


def _to_regex(pattern: str) -> re.Pattern[str]:
    out = []
    for part in re.split(r"(<[^>]+>)", pattern):
        out.append(".+" if part.startswith("<") else re.escape(part))
    return re.compile("".join(out) + r"\Z", re.IGNORECASE)


_COMPILED = [(_to_regex(k), k) for k in MULTI_VALUED]


def reason(key: str, extra: tuple[str, ...] = ()) -> str | None:
    """Why a second value of `key` is legitimate, or None if it isn't.

    `extra` holds patterns from `--multi-valued`, which may use the same
    `<placeholder>` syntax as the table.
    """
    for pattern in extra:
        if _to_regex(pattern).match(key):
            return f"--multi-valued {pattern}"
    for compiled, pattern in _COMPILED:
        if compiled.match(key):
            return MULTI_VALUED[pattern]
    return None
