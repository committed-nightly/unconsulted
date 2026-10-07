# unconsulted

Find the lines in your git config that git never consults.

git will accept any `section.key = value` you write and never validate the
name, because it only ever looks up the names it wants. So this line:

```
[core]
	autocrfl = input
```

does nothing, forever, and you find out when a colleague asks why your diffs
are full of line-ending changes. `git config --list` shows it to you. `git
config core.autocrfl` prints `input` quite happily. Nothing anywhere tells you
that no git command has ever asked for that key.

The same silence covers a value a later line overrides, an alias that loses to
a real command, and an `include.path` pointing at a file that is not there.

```
$ unconsulted check -q
~/.gitconfig:14: shadowed: user.email never applies; .git/config:8 sets it again to 'me@work.example'
~/.gitconfig:31: dead-alias: alias `lfs` never runs; `git lfs` is already a command (a git-* on your PATH)
~/.gitconfig:44: include-missing: include of '~/.gitconfig.work' loads nothing; /home/you/.gitconfig.work is not a file
```

## Install

```
pip install git+https://github.com/committed-nightly/unconsulted
```

Python 3.10 or newer, no dependencies. Needs `git` on your PATH — the tool is a
front end for it, not a reimplementation of it. See
[Why it shells out](#why-it-shells-out).

## Usage

`unconsulted check` reads the config of a repository, not a file. Most of what
it checks depends on the repository: whether the branch a `[branch ...]`
section names exists, whether `branch.x.remote` names a remote you have, which
conditional includes applied. So it works the way `git config` does, on
whatever system, global and local config applies where you run it.

There is a config with ten things wrong with it in `examples/`.
`examples/build.sh` wraps a throwaway repository around it, so everything
below runs from a fresh clone:

```
$ REPO=$(examples/build.sh)
$ unconsulted check -C "$REPO" -q
.git/config:7: case-split: [remote "origin"] is one of 2 sections differing only in case: "Origin", "origin"
.git/config:19: typo-key: core.autocrfl is not a key git documents; did you mean core.autocrlf?
.git/config:22: shadowed: core.excludesfile never applies; .git/config:23 sets it again to '~/.gitignore'
.git/config:28: dead-alias: alias `lfs` never runs; `git lfs` is already a command (a git-* on your PATH)
.git/config:35: include-missing: include of './missing.config' loads nothing; /tmp/xxx/.git/missing.config is not a file
.git/config:38: include-empty: include of './empty.config' sets nothing; the file has no config in it
.git/config:42: includeif-no-such-dir: condition `gitdir:~/definitely-not-a-real-directory/` can never match; /home/you/definitely-not-a-real-directory/ is not a directory on this machine
.git/config:47: case-split: [remote "Origin"] is one of 2 sections differing only in case: "Origin", "origin"
.git/config:52: no-such-remote: branch.deleted-last-spring.remote names remote 'upstraem', which this repository does not have
.git/config:52: stale-branch: [branch "deleted-last-spring"] has no branch; nothing here is consulted
```

Exit status is 1 when there are findings, 0 when there are none, 2 when it
could not run. Drop the `-q` and each finding explains itself and says what to
do about it.

The other question — which line actually won:

```
$ unconsulted explain core.excludesFile -C "$REPO"
core.excludesfile   every value git read, in the order it read them

     local  '~/.gitignore-old'
            .git/config:22
  -> local  '~/.gitignore'
            .git/config:23

`git config core.excludesfile` returns the arrowed value. Earlier ones are
read and discarded, unless the key is multi-valued.
```

Useful options:

```
--scope local            only findings in one scope; repeatable
--multi-valued KEY       a key of yours that is repeated on purpose
--include-undocumented   every key missing from `git help --config`, not just typos
```

## What it checks

| code | what it means |
| --- | --- |
| `shadowed` | A later line sets the same key, so this value can never be returned. |
| `typo-key` | Not a key git documents, and within a character or two of one that is. |
| `dead-alias` | `git <name>` is already a command here, and a command always beats an alias. |
| `include-missing` | The include path is not a file. git ignores this silently. |
| `include-empty` | The file is there and has no config in it. |
| `includeif-no-such-dir` | A `gitdir:` condition whose directory does not exist, so it can never match. |
| `stale-branch` | A `[branch "x"]` section with no branch `x`. |
| `no-such-remote` | `branch.x.remote` names a remote this repository does not have. |
| `case-split` | Two subsections differing only in case, which git treats as two things. |
| `undocumented-key` | Not in `git help --config` at all. Off by default; see below. |

### The one worth explaining: dead-alias

Everyone knows an alias cannot shadow a git builtin. The documented rule stops
there, and the real rule is wider. git resolves a name against its builtins,
then the commands in `git --exec-path`, then `git-<name>` anywhere on your
PATH, and only then your aliases:

```
$ git config alias.request-pull '!echo mine'
$ git request-pull
usage: git request-pull [options] start url [end]

$ git config alias.lfs '!echo mine'
$ git lfs
git-lfs/3.8.0 (GitHub; linux amd64; go 1.27.0)
```

`request-pull` is not a builtin — it is a script in git's exec path — and it
wins. `lfs` is not part of git at all; it wins because `git-lfs` is on PATH.
Neither produces a warning. A check that only knew about builtins would miss
both, which is why this one asks `git --list-cmds` instead of carrying a list.

It also means the answer is specific to the machine. `alias.lfs` is dead where
git-lfs is installed and fine where it is not.

## What it will not tell you

**A value git will reject.** `core.autocrlf = yes` is a type error that git
only reports when something reads it. Checking that needs a table of every
key's type, which git does not expose, so it is not here.

**Whether another tool reads a key.** This is the limit that shapes the
`typo-key` check, and it is worth knowing before you trust the output.

`git help --config` is git's own list of every key it understands, which makes
it the obvious oracle — except that it is generated from `Documentation/config/`
and some real keys are documented elsewhere. `filter.<driver>.process` and
`filter.<driver>.required` are in gitattributes(5) and are missing from it; so
is `submodule.<name>.path`. Those three are read by git every day.

So absence from the list is not evidence of much. A check that reported it
would tell anyone with git-lfs installed that their working `filter.lfs.process`
is dead. The default finding therefore needs something stronger — a documented
key in the same section, the same shape, within a character or two:

```
core.autocrfl        -> typo-key, because core.autocrlf exists
filter.lfs.process   -> silent, because nothing in `filter` looks like it
lfs.url              -> silent, because git has no `lfs` section at all
```

`--include-undocumented` gives you the weaker finding under a name that claims
only what is known. It will show you third-party settings, which are usually
fine.

**Whether a repeated key is a mistake.** `remote.origin.fetch` twice is a
normal remote; `user.email` twice is a bug. git reads both the same way and
exposes no way to ask which kind a key is — the knowledge lives in whether
git's C reads it into a string or a list.

So `src/unconsulted/multivalue.py` carries a table, and it is the only thing in
the tool that is asserted rather than asked. It was seeded by
`tools/regen_multivalue.py` from git-config(5) on a real machine and then
checked by hand, and every entry records the phrase it came from:

```
$ unconsulted multi-valued
Keys where a repeat is the point, not a mistake.
`shadowed` stays quiet about these. Add your own with --multi-valued.

  blame.ignoreRevsFile                     man: "may be repeated"
  core.gitProxy                            man: "may be set multiple times"
  credential.helper                        man: "multiple helpers may be defined"
  format.notes                             man: "specified multiple times"
  ...
```

A key missing from that table produces a `shadowed` finding that is wrong, so
`--multi-valued KEY` exists to patch it without waiting for us. A key wrongly
in it only means we stay quiet. Those costs are not symmetric, so the table
errs towards quiet.

## Why it shells out

Every answer comes from git: the entry list from `git config --list -z
--show-origin --show-scope`, the key list from `git help --config`, the command
list from `git --list-cmds`, the branches from `git for-each-ref`. Nothing here
parses a config file to decide anything.

That is not laziness about parsing. It is that config resolution has more edges
than it looks like — scope order, includes inside includes, conditional
includes, `[section.sub]` lowercasing its subsection while `[section "sub"]`
does not, values continued across lines — and a tool that reimplemented them
could disagree with git. A tool that disagrees with git about git's own config
is worse than no tool, because you would believe it.

There is one exception, and it is fenced in. git says which *file* an entry
came from and never which line, so `locate.py` scans the file to find the line.
It can only ever affect what is printed, never whether a finding exists, and it
checks its own work: for each file it compares how many assignments it found
with how many values git read, and reports no line number at all rather than a
plausible wrong one.

## Development

```
pip install -e ".[dev]"
pytest
ruff check .
```

The tests build real repositories and ask the real git.
`tests/test_crosscheck.py` is the one that matters: it takes a dozen awkward
config files — a key on the section line, a value continued over a newline, a
subsection containing a URL, the same key three times — asks git what it read,
and asserts that the line the scanner attributes each entry to really does
assign that variable.

## Licence

MIT.
