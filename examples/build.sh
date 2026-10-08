#!/bin/sh
# Build a throwaway repository whose config is examples/broken.config, so the
# tool has something to look at. Prints the path it made.
#
#   unconsulted check -C "$(examples/build.sh)"
#
# The repo gets one remote named `origin` and no branch called
# `deleted-last-spring`, which is what makes the case-split and stale-branch
# findings in broken.config true rather than hypothetical.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=${1:-$(mktemp -d)}

git init -q "$repo"
cd "$repo"
git -c user.name=example -c user.email=example@example.invalid \
    commit -q --allow-empty -m "an empty commit, so a branch exists"
git remote add origin https://example.invalid/right-case.git

# Next to .git/config, because that is where git resolves a relative
# include.path from -- the directory of the including file, not the work tree.
: > .git/empty.config
printf '[user]\n\temail = work@example.invalid\n' > .git/work.config

# Keep what git itself put in .git/config -- core.repositoryformatversion and
# the remote -- then append the example.
cat "$here/broken.config" >> .git/config

echo "$repo"
