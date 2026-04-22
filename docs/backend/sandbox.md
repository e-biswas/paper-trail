# Backend — Sandbox

## Purpose

A narrow abstraction every code-execution call goes through. MVP ships with a single backend, **`LocalSandbox`**, which runs commands inside a pre-staged `/tmp/<fixture>-demo/` directory. The interface is designed so a future `E2BSandbox` (or `DockerSandbox`) can drop in without touching callers.

**Zero-spend constraint:** no cloud backends in MVP. Local only.

## Status

`TODO` · last updated 2026-04-21

## Public interface

```python
# server/sandbox/base.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

@dataclass
class ExecResult:
    ok: bool                 # process returned 0 AND no timeout/oom
    returncode: int
    stdout: str              # UTF-8 decoded, lossy replace
    stderr: str
    duration_ms: int
    truncated: bool          # True if stdout/stderr was truncated to cap
    timed_out: bool

class Sandbox(Protocol):
    @property
    def workdir(self) -> Path: ...

    async def exec(
        self,
        command: str | list[str],
        *,
        timeout_s: float = 120.0,
        env: dict[str, str] | None = None,
        stdout_cap_bytes: int = 512_000,
    ) -> ExecResult: ...

    async def read_text(self, rel_path: str) -> str: ...

    async def write_text(self, rel_path: str, content: str) -> None: ...

    async def close(self) -> None: ...
```

## Backends

### `LocalSandbox` (MVP)

```python
# server/sandbox/local.py
class LocalSandbox:
    def __init__(self, workdir: Path):
        self._workdir = Path(workdir).resolve()
        if not self._workdir.exists():
            raise SandboxError(f"workdir does not exist: {self._workdir}")
```

**Safety properties it does enforce** (even though "local" is not real isolation):

- **Path confinement:** `read_text`/`write_text` resolve `rel_path` against `workdir` and reject anything that escapes (`..`, absolute paths, symlinks pointing outside). An attempt to `write_text("../../etc/passwd", ...)` raises.
- **Subprocess confinement:** `exec` runs with `cwd=self._workdir`. Never uses `shell=True`. Command is a list (preferred) or gets split via `shlex` if a string.
- **Timeout:** every `exec` has a hard `timeout_s` cap. On expiry, process is killed with `SIGKILL` and `ExecResult(timed_out=True)` returned.
- **Output cap:** stdout and stderr each truncated to `stdout_cap_bytes` (default 512 KB). `ExecResult.truncated=True` flagged. Prevents a runaway process from filling memory.
- **Environment isolation:** `exec` starts with a minimal base env (`PATH`, `HOME`, `LANG`); caller-supplied `env` merges on top. `PYTHONPATH`, `VIRTUAL_ENV`, etc. are scrubbed unless explicitly passed.
- **Read-only critical paths:** we never pass `/`, `/etc`, `/usr`, `$HOME` as a workdir. If the caller somehow tries, constructor raises.

**Safety properties it does NOT enforce** (known gaps, documented for future):

- **Network:** subprocess CAN make network calls. No egress block. Acceptable for MVP (we're on our own laptop; the fixtures we run are ones we wrote).
- **Filesystem outside workdir:** subprocess could write to `/tmp` or anywhere user has permission. Path-confinement applies only to the Sandbox API, not to arbitrary binaries the subprocess might invoke.
- **CPU/memory:** no cgroup limits. A runaway `pip install` can consume all RAM.

These are why the plan cautions: **LocalSandbox is safe enough for curated demos we wrote and for best-effort runs on repos we spot-checked. It is NOT a security sandbox for arbitrary untrusted code.** This is explicitly called out in the README's "judges can try arbitrary repos" warning.

### `E2BSandbox` (documented future slot, NOT implemented)

A stub file `server/sandbox/e2b.py` exists with the class skeleton and a clear `NotImplementedError` — so the seam for future work is visible, but we don't import or enable it.

When we do enable it (post-hackathon):
- `E2BSandbox(workdir=...)` creates an e2b cloud microVM
- `exec` calls into e2b's Python SDK
- `read_text` / `write_text` mapped to the e2b filesystem API
- No changes to any subagent code

## How callers use it

```python
# server/subagents/experiment_runner.py
async def run(sandbox: Sandbox, command: str | list[str], timeout_s: float = 120):
    result = await sandbox.exec(command, timeout_s=timeout_s)
    # parse METRIC_JSON: ... line from stdout if present
    ...
```

The `exec` tool the agent can call (via the SDK's `Bash`) is **routed through** the Sandbox rather than executing directly. This is the discipline: no subagent ever calls `subprocess.run` directly.

### Wiring the agent's `Bash` tool to the Sandbox

The Claude Agent SDK's built-in `Bash` tool runs in the SDK's current working dir by default. We configure the SDK so `cwd = sandbox.workdir`, which gives us workdir confinement for "free" on top of the standard `Bash` tool. For timeout, cap, and env scrubbing, we additionally restrict the allowed tool set to force `Bash` calls through a wrapper that constructs an `ExecResult` from the sandbox — implemented as a custom MCP tool `mcp__sandbox__exec` that the agent's tool allowlist includes in place of raw `Bash` when the run is in "strict sandbox" mode.

For MVP convenience, we accept the SDK's default `Bash` behavior (which respects `cwd`) and document the limitation. Strict sandbox mode is a Day-5 polish if there's time.

## Implementation notes

### Why a Protocol and not an ABC

Structural typing lets test doubles plug in without inheritance. A test can pass any object with `exec`, `read_text`, `write_text`, `close`, `workdir` — useful for testing subagents without spinning up a real sandbox.

### Concurrency

`LocalSandbox.exec` uses `asyncio.create_subprocess_exec` with `asyncio.wait_for(... , timeout)`. No manual threading.

### Logging

Every `exec` call logs `INFO`: command (redacted if it contains `password` / `token`), workdir, returncode, duration_ms, truncated, timed_out. `DEBUG` also logs the first 2 KB of stdout.

### Error taxonomy

- `SandboxError(RuntimeError)` — base
- `PathConfinementError` — `read_text`/`write_text` attempted to escape workdir
- `SandboxExecError` — subprocess raised before we could capture output (very rare; usually the process returncode tells the story)

## How to verify (end-to-end)

### Setup

Muchlinski fixture staged at `/tmp/muchlinski-demo`.

### Smoke tests

1. **Construct + workdir:** `LocalSandbox(Path("/tmp/muchlinski-demo"))` succeeds. `.workdir` points to that path. Instantiating on a non-existent path raises `SandboxError`.

2. **Basic exec:**
   ```python
   sb = LocalSandbox(Path("/tmp/muchlinski-demo"))
   r = await sb.exec(["python", "src/eval.py"], timeout_s=120)
   assert r.ok and "METRIC_JSON" in r.stdout
   ```

3. **Timeout:**
   ```python
   r = await sb.exec(["python", "-c", "import time; time.sleep(10)"], timeout_s=1)
   assert r.timed_out and not r.ok
   ```

4. **Output cap:**
   ```python
   r = await sb.exec(["python", "-c", "print('x' * 2_000_000)"], stdout_cap_bytes=100_000)
   assert r.truncated and len(r.stdout) <= 100_500
   ```

5. **Path confinement:**
   ```python
   with pytest.raises(PathConfinementError):
       await sb.read_text("../../../etc/passwd")
   with pytest.raises(PathConfinementError):
       await sb.write_text("/etc/evil", "...")
   ```

6. **No shell injection:**
   ```python
   r = await sb.exec(["echo", "$PATH"])
   assert r.stdout.strip() == "$PATH"   # literal dollar sign — no expansion
   ```

7. **Env scrubbing:**
   ```python
   os.environ["PYTHONPATH"] = "/evil"
   r = await sb.exec(["python", "-c", "import os; print(os.environ.get('PYTHONPATH', 'missing'))"])
   assert "missing" in r.stdout
   ```

## Open questions / deferred

- `E2BSandbox` implementation — deliberately deferred. When the user has a budget, we add it in a follow-up PR.
- `DockerSandbox` — out of scope. Overlaps with E2B at more operational cost.
- Per-call resource limits (`ulimit -v`, cgroups) — would harden LocalSandbox further. `DEFERRED`.
- Streaming stdout (incremental output as a process runs) — would make the Tool Stream UI nicer for long-running evals. `DEFERRED`; MVP uses final-result-only.
- Network egress blocking via netns. `DEFERRED`.
