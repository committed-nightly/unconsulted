from __future__ import annotations

import shutil
import subprocess

import pytest

HAVE_GIT = shutil.which("git") is not None

pytestmark = pytest.mark.skipif(not HAVE_GIT, reason="needs git")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A real git repository with nothing but its own config.

    GIT_CONFIG_NOSYSTEM and an empty GIT_CONFIG_GLOBAL keep whatever this
    machine has in /etc/gitconfig and ~/.gitconfig out of the results, so a
    test asserting a finding count is asserting something stable. The tests
    that care about scope layering set those back deliberately.
    """
    empty_global = tmp_path / "empty-global"
    empty_global.write_text("")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_global))
    # Keep an ambient GIT_DIR or similar from a surrounding git invocation out.
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG", "GIT_CONFIG_COUNT"):
        monkeypatch.delenv(var, raising=False)

    path = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(path)], check=True)

    class Repo:
        def __init__(self) -> None:
            self.path = path
            self.config = path / ".git" / "config"

        def write(self, text: str) -> None:
            """Replace .git/config, keeping the core section git needs."""
            self.config.write_text("[core]\n\trepositoryformatversion = 0\n" + text)

        def append(self, text: str) -> None:
            with self.config.open("a") as fh:
                fh.write(text)

        def git(self, *args: str) -> str:
            out = subprocess.run(
                ["git", "-C", str(path), *args], capture_output=True, text=True, check=True
            )
            return out.stdout

        def commit(self) -> None:
            self.git(
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.invalid",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "one",
            )

    return Repo()
