# Backend — FastAPI Server

## Purpose

HTTP + WebSocket front door for the backend. Boots the FastAPI app, exposes the two WebSocket endpoints (`/ws/investigate`, `/ws/check`), validates the opening `start` frame, delegates to the agent core, and forwards envelope events to the browser.

## Status

`TODO` · last updated 2026-04-21

## Public interface

### Endpoints

| Path | Method | Purpose |
|---|---|---|
| `GET /healthz` | HTTP | Liveness probe. Returns `{"ok": true}`. |
| `GET /` | HTTP | Returns a tiny HTML shell linking to the Vite dev server (nice to have; optional). |
| `WS /ws/investigate` | WebSocket | Deep Investigation runs |
| `WS /ws/check` | WebSocket | Quick Check runs |

### WebSocket lifecycle (both endpoints)

1. Client connects.
2. Client sends `start` frame (schema in [../integration.md](../integration.md)).
3. Server validates config; on failure sends `error` + closes.
4. Server sends `session_start`.
5. Server runs `run_agent(config)` (from [agent.md](agent.md)), forwarding every yielded envelope.
6. Server sends `session_end` (always, success or failure).
7. Server closes.

Client disconnects abort the run: the agent task is cancelled; any in-flight tool call is left to finish or time out (we don't kill child processes mid-flight at MVP).

## Implementation notes

### File

```python
# server/main.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from .agent import run_agent, RunConfig
from .env import load_env
import asyncio, itertools, json
from datetime import datetime, timezone
from uuid import uuid4

app = FastAPI(title="Paper Trail")

@app.on_event("startup")
async def _startup() -> None:
    load_env()  # validates required env vars, raises early

@app.get("/healthz")
async def healthz(): return {"ok": True}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

async def _run_ws(ws: WebSocket, mode: str) -> None:
    await ws.accept()
    try:
        first = await ws.receive_json()
        if first.get("type") != "start":
            await ws.send_json({"type": "error", "run_id": None, "ts": _now_iso(), "seq": 0,
                                "data": {"code": "bad_handshake", "message": "expected start frame"}})
            await ws.close()
            return
        cfg = RunConfig(mode=mode, run_id=first.get("run_id") or str(uuid4()), **first["config"])
        seq = itertools.count()

        async def send(event: dict) -> None:
            event["run_id"] = cfg.run_id
            event["ts"] = _now_iso()
            event["seq"] = next(seq)
            await ws.send_json(event)

        await send({"type": "session_start", "data": {"mode": mode}})

        async for envelope in run_agent(cfg):
            await send(envelope)

    except WebSocketDisconnect:
        return  # client bailed; agent task is cancelled via the async generator
    except Exception as exc:
        await ws.send_json({"type": "error", "run_id": None, "ts": _now_iso(), "seq": -1,
                            "data": {"code": "server_exception", "message": str(exc)}})
    finally:
        try: await ws.close()
        except Exception: pass

@app.websocket("/ws/investigate")
async def ws_investigate(ws: WebSocket) -> None: await _run_ws(ws, "investigate")

@app.websocket("/ws/check")
async def ws_check(ws: WebSocket) -> None: await _run_ws(ws, "check")
```

### Environment loading

```python
# server/env.py
import os
from pathlib import Path

REQUIRED = ["ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GITHUB_BOT_OWNER", "GITHUB_BOT_REPO"]

def load_env() -> None:
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required env: {missing}")
```

No `python-dotenv` dependency — tiny inline loader is enough.

### CORS

Dev-only: allow `http://localhost:5173` for the Vite origin. Production config deferred (out of MVP scope).

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
```

### Logging

- `uvicorn` default access log is fine for `/healthz`.
- Agent events logged at `DEBUG` to a rotating file for post-mortem; off by default.

### Why not Sockets.IO / SSE / gRPC

- Plain WebSocket is native to FastAPI, zero dependencies, and matches the frontend's built-in `WebSocket` API. No reason to add a layer.

## How to verify (end-to-end)

### Setup

```bash
cp .env.example .env
# fill secrets
uv sync
uv run uvicorn server.main:app --reload --port 8080
```

### Checks

1. **Healthcheck:** `curl http://localhost:8080/healthz` → `{"ok": true}`.
2. **Bad handshake:** connect with `websocat`, send `{"type":"hello"}` → receive `error` envelope with `code:bad_handshake`, socket closes.
3. **Deep Investigation happy path:**
   ```bash
   echo '{"type":"start","run_id":"test-001","config":{"paper_url":"...","repo_path":"/tmp/muchlinski","repo_slug":"bot/muchlinski"}}' \
     | websocat ws://localhost:8080/ws/investigate
   ```
   Expect streaming events per [../integration.md](../integration.md#example-transcript-abridged-deep-investigation). Final event is `session_end` with `ok: true`.
4. **Quick Check happy path:**
   ```bash
   echo '{"type":"start","run_id":"test-002","config":{"question":"Is imputation fit on train only?","repo_path":"/tmp/muchlinski"}}' \
     | websocat ws://localhost:8080/ws/check
   ```
   Expect exactly one `quick_check_verdict` envelope followed by `session_end`.
5. **Client disconnect mid-run:** connect, send `start`, wait for first `hypothesis`, then close the client socket. Server log shows `WebSocketDisconnect` handled cleanly; no tracebacks.

### Expected failure modes

- **500 on startup.** Usually missing env var. `load_env()` raises with the list of missing keys.
- **Socket accepts then immediately closes.** Usually a schema mismatch in the first frame. Check server logs.
- **Events arrive slowly then burst.** This is the `include_partial_messages` issue flagged as the main Day-1 risk. Escalate to the agent module.

## Planned — client-initiated stop (see TASKS D5.X-abort)

To support the UI's Abort button, the WS receive loop on both endpoints
must accept a client-originated `{"type": "stop"}` frame at any point
after `session_start`. Behavior:

- On `stop`, cancel the `asyncio.Task` holding `run_agent(config)`.
- The orchestrator (see [agent.md](agent.md)) catches `CancelledError`,
  flushes the open phase, and emits a terminal `session_end` with
  `stop_reason: "user_abort"`.
- The handler wrapper MUST NOT emit a second `session_end` of its own in
  this path — the orchestrator owns that event.

Implementation shape: replace the single `receive_json()` call at
handshake time with a small receive loop running concurrently with the
agent generator. The first frame must still be `start`; any subsequent
frames are parsed and dispatched (currently only `stop` is defined).
Unknown client frames are ignored with a warning log.

## Known gaps / corner cases

- **MAJOR — `ws.send_json` failures silently caught; agent keeps running.**
  `server/main.py:105-109` catches send failures but the `run_agent`
  generator continues yielding. Orphaned task burns tokens until SDK
  completion or timeout.
  Fix sketch: propagate the send error into the generator task via
  cancel; on next yield the orchestrator sees `CancelledError` and
  terminates cleanly.
- **MAJOR — no `asyncio.Task` handle for the generator, so disconnect
  cannot cancel the run.** Same root cause as the agent-side leak; fix
  is paired with the cancel-path work for the Abort button.
- **MINOR — no receive timeout on the initial `start` frame.**
  `server/main.py:112` blocks forever waiting for the first frame; a
  hung client can hold a connection slot indefinitely.
  Fix sketch: wrap the receive in `asyncio.timeout(30)`.
- **MINOR — no heartbeat / ping-pong on idle connections.**
  Long Deep-Investigation runs with sparse emissions can be silently
  terminated by intermediaries. Fix sketch: send a `{"type":"heartbeat"}`
  envelope every 20 s if nothing else has shipped.
- **MINOR — handshake errors return without explicit `ws.close()`.**
  `server/main.py:114-123, 128-134, 155-161` rely on the `finally`
  block; sockets linger in CLOSE_WAIT. Add an explicit `await ws.close()`
  after bad-handshake errors.
- **MINOR — CORS / WS origin check not enforced.** `allow_origins`
  includes only `http://localhost:5173`, but the WS endpoint does not
  check `Origin` independently. Fix sketch: reject in `accept` if
  `ws.headers.get("origin")` is not allowlisted.
- **MINOR — no size limits on `paper_url` / `repo_path` / `question`.**
  `RunConfig.from_dict` accepts arbitrary-length strings. A malicious
  10 MB `question` is expensive and fills logs. Cap to
  `<= 2048 / 512 / 10_000` chars respectively and reject with
  `bad_handshake` otherwise.
- **MINOR — logging doesn't carry `run_id` consistently.** Some log
  lines have it, most don't; hard to grep post-demo. Fix sketch: wrap
  the module logger in a `LoggerAdapter` bound to `run_id` for the life
  of each WS handler.

## Open questions / deferred

- Auth on WS endpoints: `DEFERRED`. Single-user demo.
- Rate limiting: not needed.
- Structured request IDs in logs: `DEFERRED`, would be nice post-hackathon.
- Graceful-shutdown semantics for in-flight runs: accept abrupt termination at MVP.
