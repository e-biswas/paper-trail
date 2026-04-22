"""FastAPI entrypoint for Paper Trail.

Two WebSocket endpoints — `/ws/investigate` for Deep Investigation runs and
`/ws/check` for Quick Check runs — share a single handler that validates the
opening `start` frame, delegates to the run orchestrator in `server.agent`, and
forwards envelope events back to the client.

See `docs/integration.md` for the on-wire schema.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from server.artifacts import (
    ArtifactError,
    build_diff_patch,
    build_dossier_md,
    build_events_jsonl,
    build_paper_md,
    session_summary,
)
from server.env import EnvError, load_env
from server.runs import get_store

Mode = Literal["investigate", "check"]

log = logging.getLogger(__name__)


# Dev frontend (Vite) runs on :5173. We keep this narrow; prod CORS is out of scope for MVP.
_DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

app = FastAPI(
    title="Paper Trail",
    version="0.1.0",
    description="A verification intern for research engineers.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEV_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _on_startup() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    load_env()
    log.info("reproducibility forensics booted; Opus 4.7 mode")


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"ok": True, "service": "paper-trail"}


@app.get("/")
async def index() -> dict[str, Any]:
    return {
        "service": "paper-trail",
        "endpoints": {
            "health": "/healthz",
            "investigate": "ws://localhost:8080/ws/investigate",
            "check": "ws://localhost:8080/ws/check",
        },
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _handle_ws(ws: WebSocket, mode: Mode) -> None:
    """Shared WebSocket handler for both endpoints.

    1. Accept the connection.
    2. Read and validate the `start` frame.
    3. Import the run orchestrator lazily so import errors don't block connection.
    4. Stream envelopes from the orchestrator to the client.
    5. Always close with a `session_end` (orchestrator is responsible for the
       final envelope; we add a safety net here).
    """
    await ws.accept()
    run_id: str | None = None
    seq = itertools.count()

    async def send(event: dict[str, Any]) -> None:
        event.setdefault("run_id", run_id or "unknown")
        event.setdefault("ts", _now_iso())
        event.setdefault("seq", next(seq))
        await ws.send_json(event)

    try:
        first = await ws.receive_json()
        if not isinstance(first, dict) or first.get("type") != "start":
            await send(
                {
                    "type": "error",
                    "data": {
                        "code": "bad_handshake",
                        "message": "first frame must be {\"type\": \"start\", ...}",
                    },
                }
            )
            return

        run_id = first.get("run_id") or str(uuid4())
        config_raw = first.get("config") or {}
        if not isinstance(config_raw, dict):
            await send(
                {
                    "type": "error",
                    "data": {"code": "bad_handshake", "message": "`config` must be an object"},
                }
            )
            return

        await send({"type": "session_start", "data": {"mode": mode}})

        # Lazy import so FastAPI boots even if the orchestrator's dependencies are missing
        # (e.g. running a reduced dev mode without the Agent SDK present).
        try:
            from server.agent import RunConfig, run_agent
        except Exception as exc:  # pragma: no cover — surface any import-time error
            log.exception("failed to import run_agent")
            await send(
                {
                    "type": "error",
                    "data": {"code": "import_error", "message": str(exc)},
                }
            )
            return

        try:
            config = RunConfig.from_dict(mode=mode, run_id=run_id, raw=config_raw)
        except ValueError as exc:
            await send(
                {
                    "type": "error",
                    "data": {"code": "bad_config", "message": str(exc)},
                }
            )
            return

        # Run the orchestrator in a background task so we can concurrently
        # watch the WebSocket for client-initiated `{"type": "stop"}` frames
        # (the D5.X-abort contract — see docs/integration.md).
        agent_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def _pump() -> None:
            """Drive the orchestrator and push envelopes onto the queue."""
            try:
                async for envelope in run_agent(config):
                    await agent_queue.put(envelope)
            finally:
                await agent_queue.put(None)  # sentinel: generator done

        run_task = asyncio.create_task(_pump(), name=f"agent-{run_id}")
        client_stopped = False

        async def _watch_client() -> None:
            """Watch for a client-originated stop frame or a disconnect.

            When either arrives, cancel the run task; the orchestrator's
            CancelledError handler emits a terminal `session_end` with
            `stop_reason="user_abort"`.
            """
            nonlocal client_stopped
            try:
                while True:
                    frame = await ws.receive_json()
                    if isinstance(frame, dict) and frame.get("type") == "stop":
                        client_stopped = True
                        log.info("ws client sent stop frame (run_id=%s)", run_id)
                        run_task.cancel()
                        return
                    log.debug("ignoring unknown client frame: %s", frame)
            except WebSocketDisconnect:
                if not run_task.done():
                    log.info(
                        "ws client disconnected mid-run (run_id=%s) — cancelling agent",
                        run_id,
                    )
                    run_task.cancel()
            except Exception:
                log.debug("watch_client ended", exc_info=True)

        watch_task = asyncio.create_task(_watch_client(), name=f"watch-{run_id}")

        try:
            while True:
                envelope = await agent_queue.get()
                if envelope is None:
                    break
                # Only the abort path can inject user_abort; harden against
                # orchestrator reporting that without a real client stop.
                if (
                    envelope.get("type") == "session_end"
                    and envelope.get("data", {}).get("stop_reason") == "user_abort"
                    and not client_stopped
                ):
                    envelope["data"]["stop_reason"] = "client_disconnect"
                await send(envelope)
        finally:
            watch_task.cancel()
            try:
                await asyncio.shield(asyncio.wait_for(run_task, timeout=0.5))
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:
                log.debug("run_task final drain raised", exc_info=True)

    except WebSocketDisconnect:
        log.info("ws client disconnected (run_id=%s, mode=%s)", run_id, mode)
    except Exception as exc:
        log.exception("unhandled ws exception")
        try:
            await send(
                {
                    "type": "error",
                    "data": {"code": "server_exception", "message": str(exc)},
                }
            )
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@app.websocket("/ws/investigate")
async def ws_investigate(ws: WebSocket) -> None:
    await _handle_ws(ws, "investigate")


@app.websocket("/ws/check")
async def ws_check(ws: WebSocket) -> None:
    await _handle_ws(ws, "check")


# ──────────────────────────────────────────────────────────────────────────
# Run + session REST endpoints — used by the frontend for history, usage,
# and artifact downloads.
# ──────────────────────────────────────────────────────────────────────────


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    store = get_store()
    meta = store.load_meta(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    from dataclasses import asdict
    return asdict(meta)


@app.get("/runs/{run_id}/events.jsonl", response_class=PlainTextResponse)
async def get_events(run_id: str) -> str:
    try:
        return build_events_jsonl(run_id)
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs/{run_id}/dossier.md", response_class=PlainTextResponse)
async def get_dossier(run_id: str) -> str:
    try:
        return build_dossier_md(run_id)
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs/{run_id}/diff.patch", response_class=PlainTextResponse)
async def get_diff(run_id: str) -> str:
    try:
        return build_diff_patch(run_id)
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs/{run_id}/paper.md", response_class=PlainTextResponse)
async def get_paper(run_id: str) -> str:
    try:
        return build_paper_md(run_id)
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/runs/{run_id}/validate")
async def validate_run(run_id: str, force: bool = False) -> dict[str, Any]:
    """Run the Validator subagent against a completed Deep Investigation.

    Returns the `ValidityReport` payload (overall + summary + per-check marks).
    Caches: if the run already has a validity_report and `force=false` (default),
    returns the cached report without re-running the subagent.
    """
    store = get_store()
    meta = store.load_meta(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="unknown run_id")

    if meta.mode != "investigate":
        raise HTTPException(
            status_code=400,
            detail="validator is only meaningful for Deep Investigation runs "
                   f"(this run is mode={meta.mode})",
        )

    # Serve cached result when available.
    if meta.validity_report and not force:
        return {
            "cached": True,
            "cost_usd": meta.validity_cost_usd,
            "duration_ms": meta.validity_duration_ms,
            **meta.validity_report,
        }

    # Assemble inputs from the persisted run.
    transcript_parts: list[str] = []
    for ev in store.iter_events(run_id):
        etype = ev.get("type")
        data = ev.get("data") or {}
        # Reconstruct the investigator transcript from high-level events
        # (we persist parsed events, not raw text). This is a compact view
        # that retains the decision-relevant content the validator needs.
        if etype == "claim_summary":
            transcript_parts.append(f"## Claim:\nclaim: {data.get('claim', '')!r}\n")
        elif etype == "hypothesis":
            transcript_parts.append(
                f"## Hypothesis {data.get('rank', '?')}: {data.get('name', '')}\n"
                f"id: {data.get('id')}\n"
                f"confidence: {data.get('confidence')}\n"
                f"reason: {data.get('reason', '')!r}\n"
            )
        elif etype == "hypothesis_update":
            transcript_parts.append(
                f"## Hypothesis update ({data.get('id')}):\n"
                f"confidence: {data.get('confidence')}\n"
                f"reason_delta: {data.get('reason_delta', '')!r}\n"
            )
        elif etype == "check":
            transcript_parts.append(
                f"## Check: {data.get('id')}\n"
                f"hypothesis_id: {data.get('hypothesis_id')}\n"
                f"description: {data.get('description', '')!r}\n"
                f"method: {data.get('method', '')!r}\n"
            )
        elif etype == "finding":
            transcript_parts.append(
                f"## Finding: {data.get('id')}\n"
                f"check_id: {data.get('check_id')}\n"
                f"result: {data.get('result', '')!r}\n"
                f"supports: {data.get('supports', [])}\n"
                f"refutes: {data.get('refutes', [])}\n"
            )
        elif etype == "verdict":
            transcript_parts.append(
                f"## Verdict:\n"
                f"hypothesis_id: {data.get('hypothesis_id')}\n"
                f"confidence: {data.get('confidence')}\n"
                f"summary: {data.get('summary', '')!r}\n"
            )
        elif etype == "fix_applied":
            transcript_parts.append(
                f"## Fix applied:\n"
                f"files_changed: {data.get('files_changed', [])}\n"
                f"diff_summary: {data.get('diff_summary', '')!r}\n"
            )
        elif etype == "metric_delta":
            transcript_parts.append(
                f"## Metric delta:\n"
                f"metric: {data.get('metric', '')!r}\n"
                f"before: {data.get('before')}\n"
                f"after: {data.get('after')}\n"
                f"context: {data.get('context', '')!r}\n"
            )
        elif etype == "dossier_section":
            transcript_parts.append(
                f"## Dossier — {data.get('section', '').replace('_', ' ')}:\n"
                f"{data.get('markdown', '')}\n"
            )
        elif etype == "pr_opened":
            transcript_parts.append(
                f"## PR opened:\n"
                f"url: {data.get('url', '')!r}\n"
                f"title: {data.get('title', '')!r}\n"
            )

    transcript = "\n".join(transcript_parts).strip()
    if not transcript:
        raise HTTPException(
            status_code=409,
            detail="this run has no investigator events persisted; "
                   "cannot audit an empty transcript",
        )

    # Paper context — best effort.
    paper_context = ""
    try:
        paper_context = build_paper_md(run_id)
    except ArtifactError:
        paper_context = f"(no paper was attached for this run; paper_url was {meta.paper_url!r})"

    # Diff — best effort.
    diff_text: str | None = None
    try:
        diff_text = build_diff_patch(run_id)
    except ArtifactError:
        diff_text = None

    config_summary = (
        f"mode: {meta.mode}\n"
        f"repo_path: {meta.repo_path}\n"
        f"paper_url: {meta.paper_url}\n"
        f"repo_slug: {meta.repo_slug}\n"
        f"files_changed: {meta.files_changed}\n"
        f"PR: {meta.pr_url or '(none opened)'}\n"
        f"cost_usd: {meta.cost_usd}\n"
        f"total_turns: {meta.total_turns}\n"
    )

    # Spawn the validator.
    from server.subagents import validator

    result = await validator.validate(
        paper_context=paper_context,
        run_transcript=transcript,
        run_config_summary=config_summary,
        diff_text=diff_text,
    )

    if not result.ok:
        log.warning("validator failed for run %s: %s", run_id, result.error)
        raise HTTPException(
            status_code=502,
            detail=f"validator failed: {result.summary} ({result.error or 'no detail'})",
        )

    # Persist onto the run's meta so subsequent calls return cached.
    meta.validity_report = result.payload
    meta.validity_cost_usd = result.cost_usd
    meta.validity_duration_ms = result.duration_ms
    store._save_meta(meta)

    return {
        "cached": False,
        "cost_usd": result.cost_usd,
        "duration_ms": result.duration_ms,
        **result.payload,
    }


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    return session_summary(session_id)


@app.get("/sessions")
async def list_sessions() -> dict[str, Any]:
    """All sessions on disk, sorted pinned-first then by last activity."""
    store = get_store()
    docs = store.list_all_sessions()
    items: list[dict[str, Any]] = []
    for doc in docs:
        sid = doc.get("session_id")
        if not sid:
            continue
        try:
            summary = session_summary(sid)
        except Exception as exc:
            log.warning("failed to summarize session %s: %s", sid, exc)
            continue
        if summary["n_runs"] == 0:
            # Skip empty sessions — they only exist because the UI called
            # newSession() and then navigated away. Sparse and uninteresting.
            continue
        items.append(summary)
    return {"sessions": items}


@app.post("/sessions/{session_id}/pin")
async def pin_session(session_id: str, pinned: bool = True) -> dict[str, Any]:
    """Toggle the pinned flag on a session. Pinned sessions sort to the top."""
    store = get_store()
    doc = store.set_session_pinned(session_id, pinned)
    return {"session_id": session_id, "pinned": bool(doc.get("pinned", False))}


@app.post("/sessions/{session_id}/title")
async def rename_session(session_id: str, title: str | None = None) -> dict[str, Any]:
    """Rename a session. Empty / missing title resets to default auto-title."""
    store = get_store()
    doc = store.set_session_title(session_id, title)
    return {"session_id": session_id, "title": doc.get("title")}


# ──────────────────────────────────────────────────────────────────────────
# Paper upload — lets the frontend submit a PDF directly when the URL is
# behind Cloudflare / a paywall / otherwise unfetchable. Saved locally; the
# client gets back a path it can pass as `paper_url` in a Deep Investigation
# start frame (the paper ingester handles local paths).
# ──────────────────────────────────────────────────────────────────────────

# Where uploaded PDFs live. Kept under the same cache tree as auto-ingested
# papers so cleanup is a single directory.
_UPLOAD_DIR = Path(os.environ.get(
    "REPRO_UPLOAD_DIR",
    str(Path.home() / ".cache" / "paper-trail" / "uploads"),
))
_MAX_UPLOAD_BYTES = 30 * 1024 * 1024   # 30 MB — plenty for any real paper


# ──────────────────────────────────────────────────────────────────────────
# Repo attach — one-input flow that resolves a GitHub URL/slug or local path
# into both `repo_path` and `repo_slug` fields. The UI calls this from the
# composer; the result is stored client-side and fed into the WS start frame.
# ──────────────────────────────────────────────────────────────────────────


@app.post("/repos/attach")
async def attach_repo(input: str) -> dict[str, Any]:
    """Resolve a GitHub URL / slug / local path into a local dir + slug.

    Remote repos are cloned (shallow, single-branch) under
    `~/.cache/paper-trail/repos/` on first use and reused thereafter.

    Response shape:
        {
          "local_path": "/abs/path/to/repo",
          "slug": "owner/repo" | null,
          "default_branch": "main" | null,
          "source": "clone" | "cache" | "local",
          "already_cloned": true/false,
          "warning": "string" | null
        }
    """
    from server.repos import RepoAttachError, resolve_repo

    try:
        resolved = resolve_repo(input)
    except RepoAttachError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("repo attach failed")
        raise HTTPException(status_code=500, detail=f"internal error: {exc}") from exc

    return {
        "local_path": str(resolved.local_path),
        "slug": resolved.slug,
        "default_branch": resolved.default_branch,
        "source": resolved.source,
        "already_cloned": resolved.already_cloned,
        "warning": resolved.warning,
    }


@app.post("/papers/upload")
async def upload_paper(file: UploadFile = File(...)) -> dict[str, Any]:
    """Accept a PDF upload and return a local path usable as `paper_url`.

    Response shape:
        {
          "path": "/abs/path/to/paper.pdf",
          "filename": "original-name.pdf",
          "size_bytes": 568247
        }
    """
    # Sanity check content type. Not strictly reliable, but enough to catch
    # obvious mistakes (someone uploading a JPG by accident).
    if file.content_type and "pdf" not in file.content_type.lower():
        raise HTTPException(
            status_code=400,
            detail=f"expected a PDF, got content_type={file.content_type!r}",
        )

    # Read with a size cap so we don't OOM on a pathological upload.
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds {_MAX_UPLOAD_BYTES // (1024*1024)} MB limit",
        )
    if not data[:5].startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="file does not appear to be a PDF")

    # Save under a short content-hash so repeat uploads of the same paper
    # don't litter the cache.
    import hashlib
    digest = hashlib.sha256(data).hexdigest()[:16]
    safe_name = "".join(
        c for c in (file.filename or "paper.pdf")
        if c.isalnum() or c in "._-"
    ).lstrip(".") or "paper.pdf"
    filename = f"{digest}_{safe_name}"

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = _UPLOAD_DIR / filename
    path.write_bytes(data)

    return {
        "path": str(path),
        "filename": file.filename,
        "size_bytes": len(data),
        "sha256_prefix": digest,
    }


@app.get("/usage")
async def get_usage(session_id: str | None = None) -> dict[str, Any]:
    if session_id:
        return session_summary(session_id)
    # Global view (all sessions on disk) — nice for admin/debug.
    store = get_store()
    sessions_dir = store.root / "sessions"
    if not sessions_dir.exists():
        return {"total_cost_usd": 0.0, "n_runs": 0, "sessions": []}
    items: list[dict[str, Any]] = []
    total_cost = 0.0
    total_runs = 0
    for p in sessions_dir.glob("*.json"):
        sid = p.stem
        try:
            summary = session_summary(sid)
        except Exception:
            continue
        items.append(summary)
        total_cost += summary.get("total_cost_usd", 0.0)
        total_runs += summary.get("n_runs", 0)
    return {
        "total_cost_usd": round(total_cost, 4),
        "n_runs": total_runs,
        "sessions": items,
    }


def main() -> None:
    """Entry point for `python -m server.main`. Useful for ad-hoc local runs."""
    import uvicorn

    uvicorn.run(
        "server.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8080")),
        reload=os.environ.get("RELOAD", "1") == "1",
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()


def _dispatch_factory() -> Callable[[WebSocket, Mode], Awaitable[None]]:
    """Alias used only by tests to monkeypatch the shared handler if needed."""
    return _handle_ws
