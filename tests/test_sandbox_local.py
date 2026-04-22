"""Safety + functional tests for `LocalSandbox`.

Implements every bullet in docs/backend/sandbox.md#how-to-verify-end-to-end.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from server.sandbox import (
    LocalSandbox,
    PathConfinementError,
    SandboxError,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    # Seed the workdir with a file we can read/grep for confinement tests.
    (tmp_path / "readme.txt").write_text("hello world\n", encoding="utf-8")
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "main.py").write_text("print('ok')\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def sandbox(workdir: Path) -> LocalSandbox:
    return LocalSandbox(workdir)


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def test_construct_happy(workdir: Path) -> None:
    sb = LocalSandbox(workdir)
    assert sb.workdir == workdir.resolve()


def test_construct_nonexistent_raises(tmp_path: Path) -> None:
    with pytest.raises(SandboxError):
        LocalSandbox(tmp_path / "no-such-dir")


def test_construct_refuses_system_root() -> None:
    with pytest.raises(SandboxError):
        LocalSandbox("/")


def test_construct_refuses_etc() -> None:
    with pytest.raises(SandboxError):
        LocalSandbox("/etc")


def test_construct_refuses_home(monkeypatch: pytest.MonkeyPatch) -> None:
    home = Path(os.path.expanduser("~")).resolve()
    # $HOME should always exist
    with pytest.raises(SandboxError):
        LocalSandbox(home)


# --------------------------------------------------------------------------- #
# Exec — basics
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_exec_happy_path_returncode_zero(sandbox: LocalSandbox) -> None:
    r = await sandbox.exec(["python", "-c", "print('hello')"])
    assert r.ok is True
    assert r.returncode == 0
    assert "hello" in r.stdout
    assert r.timed_out is False
    assert r.truncated is False


@pytest.mark.asyncio
async def test_exec_nonzero_returncode(sandbox: LocalSandbox) -> None:
    r = await sandbox.exec(["python", "-c", "import sys; sys.exit(7)"])
    assert r.ok is False
    assert r.returncode == 7
    assert r.timed_out is False


@pytest.mark.asyncio
async def test_exec_string_command_gets_shlex_split(sandbox: LocalSandbox) -> None:
    r = await sandbox.exec("python -c \"print('foo')\"")
    assert r.ok is True
    assert "foo" in r.stdout


@pytest.mark.asyncio
async def test_exec_runs_in_workdir(sandbox: LocalSandbox) -> None:
    r = await sandbox.exec(["python", "-c", "import os; print(os.getcwd())"])
    assert r.ok
    assert str(sandbox.workdir.resolve()) in r.stdout


# --------------------------------------------------------------------------- #
# Exec — safety
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_exec_timeout_kills_process(sandbox: LocalSandbox) -> None:
    r = await sandbox.exec(
        ["python", "-c", "import time; time.sleep(10)"],
        timeout_s=0.5,
    )
    assert r.timed_out is True
    assert r.ok is False
    # Typical SIGKILL exit code path — don't lock to a specific value.


@pytest.mark.asyncio
async def test_exec_stdout_cap(sandbox: LocalSandbox) -> None:
    r = await sandbox.exec(
        ["python", "-c", "import sys; sys.stdout.write('x' * 1_000_000); sys.stdout.flush()"],
        stdout_cap_bytes=10_000,
    )
    assert r.truncated is True
    assert len(r.stdout) <= 10_500
    assert "x" in r.stdout


@pytest.mark.asyncio
async def test_exec_does_not_expand_shell_vars(sandbox: LocalSandbox) -> None:
    r = await sandbox.exec(["echo", "$PATH"])
    assert r.ok
    assert r.stdout.strip() == "$PATH"


@pytest.mark.asyncio
async def test_exec_scrubs_env(sandbox: LocalSandbox, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/evil")
    monkeypatch.setenv("VIRTUAL_ENV", "/evil/venv")
    r = await sandbox.exec(
        [
            "python", "-c",
            "import os; print('PYTHONPATH=' + os.environ.get('PYTHONPATH', 'missing')); "
            "print('VIRTUAL_ENV=' + os.environ.get('VIRTUAL_ENV', 'missing'))",
        ],
    )
    assert "PYTHONPATH=missing" in r.stdout
    assert "VIRTUAL_ENV=missing" in r.stdout


@pytest.mark.asyncio
async def test_exec_accepts_extra_env(sandbox: LocalSandbox) -> None:
    r = await sandbox.exec(
        ["python", "-c", "import os; print(os.environ.get('MY_VAR', 'missing'))"],
        env={"MY_VAR": "hello"},
    )
    assert "hello" in r.stdout


@pytest.mark.asyncio
async def test_exec_empty_command_raises(sandbox: LocalSandbox) -> None:
    from server.sandbox import SandboxExecError
    with pytest.raises(SandboxExecError):
        await sandbox.exec([])


# --------------------------------------------------------------------------- #
# read_text / write_text confinement
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_read_text_happy(sandbox: LocalSandbox) -> None:
    content = await sandbox.read_text("readme.txt")
    assert content == "hello world\n"


@pytest.mark.asyncio
async def test_read_text_absolute_rejected(sandbox: LocalSandbox) -> None:
    with pytest.raises(PathConfinementError):
        await sandbox.read_text("/etc/passwd")


@pytest.mark.asyncio
async def test_read_text_dotdot_rejected(sandbox: LocalSandbox) -> None:
    with pytest.raises(PathConfinementError):
        await sandbox.read_text("../../../etc/passwd")


@pytest.mark.asyncio
async def test_read_text_empty_rejected(sandbox: LocalSandbox) -> None:
    with pytest.raises(PathConfinementError):
        await sandbox.read_text("")


@pytest.mark.asyncio
async def test_write_text_creates_file(sandbox: LocalSandbox) -> None:
    await sandbox.write_text("notes/new.md", "hello")
    assert (sandbox.workdir / "notes" / "new.md").read_text() == "hello"


@pytest.mark.asyncio
async def test_write_text_dotdot_rejected(sandbox: LocalSandbox) -> None:
    with pytest.raises(PathConfinementError):
        await sandbox.write_text("../escape.txt", "data")


@pytest.mark.asyncio
async def test_write_text_absolute_rejected(sandbox: LocalSandbox) -> None:
    with pytest.raises(PathConfinementError):
        await sandbox.write_text("/tmp/escape.txt", "data")


# --------------------------------------------------------------------------- #
# Close is idempotent
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_close_is_noop(sandbox: LocalSandbox) -> None:
    assert await sandbox.close() is None
    assert await sandbox.close() is None
