"""Run persistence + session store.

Each WS run is recorded to disk as a directory:

    {run_root}/{run_id}/
      meta.json        # RunConfig + timing + cost, kept up-to-date incrementally
      events.jsonl     # every envelope emitted during the run, in order
      (written on first envelope; finalized on session_end)

Sessions (chat conversations that group runs together) are tracked in a
lightweight index file:

    {run_root}/sessions/{session_id}.json
      {
        "session_id": "...",
        "created_at": "...",
        "run_ids": ["run-1", "run-2", ...]
      }

Design notes:
- We deliberately don't use a database. JSONL + small JSON files are
  human-inspectable, atomic-ish via `tmp + rename`, and durable enough for
  a hackathon.
- The `RunStore` is not thread-safe across processes; we run one FastAPI
  worker. Within a process, writes happen from the WS handler coroutine.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


DEFAULT_ROOT = Path(
    os.environ.get(
        "REPRO_RUN_ROOT",
        str(Path.home() / ".paper-trail" / "runs"),
    )
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic_write(path: Path, content: str) -> None:
    """Write `content` to `path` atomically via tempfile + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", delete=False, dir=str(path.parent), suffix=".tmp", encoding="utf-8",
    ) as tf:
        tf.write(content)
        tmp_path = Path(tf.name)
    os.replace(tmp_path, path)


# --------------------------------------------------------------------------- #
# RunStore
# --------------------------------------------------------------------------- #


@dataclass
class RunMeta:
    """Lightweight header describing one run, kept up-to-date incrementally."""

    run_id: str
    mode: str                                   # "investigate" | "check"
    session_id: str | None
    config: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    finished_at: str | None = None
    cost_usd: float = 0.0
    total_turns: int = 0
    duration_ms: int = 0
    ok: bool | None = None
    pr_url: str | None = None
    # Termination class — lets follow-up runs decide whether to splice in
    # warm-start context. Populated from the orchestrator's synthesized
    # `aborted` envelope + session_end.stop_reason.
    stop_reason: str | None = None       # from session_end.data.stop_reason
    aborted_reason: str | None = None    # from aborted.data.reason
    aborted_detail: str | None = None    # from aborted.data.detail
    # Derived / cached highlights so we can splice context into follow-up prompts
    # without re-parsing the entire event log each time.
    verdict_summary: str | None = None
    verdict_confidence: float | None = None
    verdict_hypothesis_id: str | None = None
    files_changed: list[str] = field(default_factory=list)
    metric_deltas: list[dict[str, Any]] = field(default_factory=list)
    paper_url: str | None = None
    repo_path: str | None = None
    repo_slug: str | None = None
    model: str | None = None
    # Per-phase wall-clock timings (ms). Populated from phase_end envelopes.
    phase_timings: dict[str, int] = field(default_factory=dict)
    # Validator output — populated when the user triggers /runs/{id}/validate.
    validity_report: dict[str, Any] | None = None
    validity_cost_usd: float = 0.0
    validity_duration_ms: int = 0


class RunStore:
    """Manages on-disk persistence of runs + sessions."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "sessions").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Paths
    # ------------------------------------------------------------------ #

    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def events_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.jsonl"

    def meta_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "meta.json"

    def session_path(self, session_id: str) -> Path:
        return self.root / "sessions" / f"{session_id}.json"

    # ------------------------------------------------------------------ #
    # Write path
    # ------------------------------------------------------------------ #

    def begin_run(
        self,
        *,
        run_id: str,
        mode: str,
        session_id: str | None,
        config: dict[str, Any],
    ) -> RunMeta:
        """Create the run dir, initial meta.json, and append the run_id to the session."""
        meta = RunMeta(
            run_id=run_id,
            mode=mode,
            session_id=session_id,
            config=_sanitize_config(config),
            created_at=_now_iso(),
            paper_url=config.get("paper_url"),
            repo_path=config.get("repo_path"),
            repo_slug=config.get("repo_slug"),
            model=config.get("model"),
        )
        self.run_dir(run_id).mkdir(parents=True, exist_ok=True)
        # Open events.jsonl fresh
        self.events_path(run_id).write_text("", encoding="utf-8")
        self._save_meta(meta)
        if session_id:
            self._append_run_to_session(session_id, run_id)
        log.info("run begin: run_id=%s session_id=%s mode=%s", run_id, session_id, mode)
        return meta

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        """Append one envelope to the run's event log."""
        path = self.events_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str))
            f.write("\n")

    def update_meta_from_event(self, run_id: str, event: dict[str, Any]) -> None:
        """Incrementally update meta.json with details from certain envelopes.

        This keeps meta.json cheap to read without having to re-scan the event
        log when the frontend asks for a session summary.
        """
        meta = self.load_meta(run_id)
        if meta is None:
            return

        etype = event.get("type")
        data = event.get("data") or {}

        if etype == "verdict":
            meta.verdict_summary = data.get("summary")
            meta.verdict_confidence = data.get("confidence")
            meta.verdict_hypothesis_id = data.get("hypothesis_id")
        elif etype == "fix_applied":
            meta.files_changed = list(data.get("files_changed") or [])
        elif etype == "metric_delta":
            meta.metric_deltas.append({
                "metric": data.get("metric"),
                "before": data.get("before"),
                "after": data.get("after"),
                "context": data.get("context"),
            })
        elif etype == "pr_opened":
            meta.pr_url = data.get("url")
        elif etype == "aborted":
            reason = data.get("reason")
            detail = data.get("detail")
            if isinstance(reason, str):
                meta.aborted_reason = reason
            if isinstance(detail, str):
                meta.aborted_detail = detail
        elif etype == "phase_end":
            phase = data.get("phase")
            duration_ms = data.get("duration_ms")
            if isinstance(phase, str) and isinstance(duration_ms, (int, float)):
                meta.phase_timings[phase] = int(duration_ms)
        elif etype == "session_end":
            meta.ok = bool(data.get("ok", True))
            meta.cost_usd = float(data.get("cost_usd", 0.0) or 0.0)
            meta.total_turns = int(data.get("total_turns", 0) or 0)
            meta.duration_ms = int(data.get("duration_ms", 0) or 0)
            meta.finished_at = _now_iso()
            stop_reason = data.get("stop_reason")
            if isinstance(stop_reason, str):
                meta.stop_reason = stop_reason

        self._save_meta(meta)

    # ------------------------------------------------------------------ #
    # Read path
    # ------------------------------------------------------------------ #

    def load_meta(self, run_id: str) -> RunMeta | None:
        path = self.meta_path(run_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return RunMeta(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            log.warning("meta for %s is malformed: %s", run_id, exc)
            return None

    def iter_events(self, run_id: str):
        path = self.events_path(run_id)
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def load_session(self, session_id: str) -> dict[str, Any]:
        path = self.session_path(session_id)
        if not path.exists():
            return {
                "session_id": session_id,
                "created_at": _now_iso(),
                "run_ids": [],
                "pinned": False,
                "title": None,
            }
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "session_id": session_id,
                "created_at": _now_iso(),
                "run_ids": [],
                "pinned": False,
                "title": None,
            }
        # Backfill new fields for older session files.
        doc.setdefault("pinned", False)
        doc.setdefault("title", None)
        return doc

    def list_all_sessions(self) -> list[dict[str, Any]]:
        """All session docs sorted by most-recent-activity first.

        Pinned sessions always bubble to the top.
        """
        sessions_dir = self.root / "sessions"
        if not sessions_dir.exists():
            return []
        docs: list[dict[str, Any]] = []
        for p in sessions_dir.glob("*.json"):
            try:
                doc = self.load_session(p.stem)
            except Exception:
                continue
            docs.append(doc)
        def _sort_key(d: dict[str, Any]) -> tuple[int, str]:
            activity = d.get("updated_at") or d.get("created_at") or ""
            return (0 if d.get("pinned") else 1, activity)
        # Sort: pinned first (0 before 1), then newest activity first (descending string sort)
        docs.sort(key=lambda d: (_sort_key(d)[0], -_timestamp_sort_value(_sort_key(d)[1])))
        return docs

    def set_session_pinned(self, session_id: str, pinned: bool) -> dict[str, Any]:
        doc = self.load_session(session_id)
        doc["pinned"] = bool(pinned)
        doc["updated_at"] = _now_iso()
        doc.setdefault("created_at", _now_iso())
        doc.setdefault("session_id", session_id)
        doc.setdefault("run_ids", [])
        _atomic_write(
            self.session_path(session_id),
            json.dumps(doc, ensure_ascii=False, indent=2),
        )
        return doc

    def set_session_title(self, session_id: str, title: str | None) -> dict[str, Any]:
        doc = self.load_session(session_id)
        doc["title"] = title if (title and title.strip()) else None
        doc["updated_at"] = _now_iso()
        doc.setdefault("created_at", _now_iso())
        doc.setdefault("session_id", session_id)
        doc.setdefault("run_ids", [])
        _atomic_write(
            self.session_path(session_id),
            json.dumps(doc, ensure_ascii=False, indent=2),
        )
        return doc

    def list_session_runs(self, session_id: str) -> list[RunMeta]:
        session = self.load_session(session_id)
        metas: list[RunMeta] = []
        for run_id in session.get("run_ids", []):
            meta = self.load_meta(run_id)
            if meta is not None:
                metas.append(meta)
        return metas

    def recent_verdicts_for_session(
        self, session_id: str, limit: int = 5,
    ) -> list[RunMeta]:
        """Return up to `limit` recent runs for a session, sorted oldest→newest.

        The orchestrator uses this to build a 'prior findings in this
        session' context block for follow-up prompts.
        """
        runs = self.list_session_runs(session_id)
        runs.sort(key=lambda m: m.created_at)
        return runs[-limit:]

    def summarize_partial_progress(
        self, run_id: str, *, max_hypotheses: int = 3, max_checks: int = 4,
        max_files: int = 8,
    ) -> dict[str, Any] | None:
        """Walk `run_id`'s events.jsonl and return a compact summary of what
        the agent produced before it stopped.

        Used when a session's immediate prior run was aborted (typically at
        `turn_cap`) to build a warm-start block for the follow-up prompt.
        Returns None when the run has no persisted events.

        Shape:
            {
              "hypotheses": [
                {"id","rank","name","confidence","reason","reason_delta"},
                ...
              ],
              "checks": [
                {"id","hypothesis_id","description","method","finding": "..."},
                ...
              ],
              "files_inspected": ["src/prepare_data.py", ...],
              "last_event_type": "tool_call" | "hypothesis" | ...,
              "total_events": <int>,
            }
        """
        hypotheses: dict[str, dict[str, Any]] = {}
        checks_by_id: dict[str, dict[str, Any]] = {}
        files_seen: list[str] = []
        files_set: set[str] = set()
        last_type: str | None = None
        total = 0

        for ev in self.iter_events(run_id):
            total += 1
            etype = ev.get("type")
            data = ev.get("data") or {}
            if not isinstance(etype, str):
                continue
            if etype != "cost_update" and etype != "raw_text_delta":
                # These are high-cardinality + carry no structural meaning;
                # leave `last_type` pointing at the last *meaningful* event.
                last_type = etype

            if etype == "hypothesis":
                hid = str(data.get("id") or "")
                if not hid:
                    continue
                hypotheses[hid] = {
                    "id": hid,
                    "rank": int(data.get("rank") or 0),
                    "name": str(data.get("name") or ""),
                    "confidence": float(data.get("confidence") or 0.0),
                    "reason": str(data.get("reason") or ""),
                    "reason_delta": "",
                }
            elif etype == "hypothesis_update":
                hid = str(data.get("id") or "")
                if hid in hypotheses:
                    try:
                        hypotheses[hid]["confidence"] = float(
                            data.get("confidence") or hypotheses[hid]["confidence"]
                        )
                    except (TypeError, ValueError):
                        pass
                    hypotheses[hid]["reason_delta"] = str(data.get("reason_delta") or "")
            elif etype == "check":
                cid = str(data.get("id") or "")
                if not cid:
                    continue
                checks_by_id[cid] = {
                    "id": cid,
                    "hypothesis_id": str(data.get("hypothesis_id") or ""),
                    "description": str(data.get("description") or ""),
                    "method": str(data.get("method") or ""),
                    "finding": None,
                }
            elif etype == "finding":
                cid = str(data.get("check_id") or "")
                if cid in checks_by_id:
                    checks_by_id[cid]["finding"] = str(data.get("result") or "")
            elif etype == "tool_call":
                tool_input = data.get("input") or {}
                # Capture file-path hints; many tools (Read/Edit/Write/Grep)
                # put the path under one of these keys.
                for key in ("file_path", "path", "file"):
                    val = tool_input.get(key) if isinstance(tool_input, dict) else None
                    if isinstance(val, str) and val and val not in files_set:
                        files_seen.append(val)
                        files_set.add(val)
                        break

        if total == 0:
            return None

        # Rank-sort hypotheses by last-known confidence (desc); cap.
        ranked = sorted(
            hypotheses.values(),
            key=lambda h: (-float(h["confidence"]), h["rank"]),
        )[:max_hypotheses]

        # Checks: prefer ones that have a finding; cap.
        checks_list = list(checks_by_id.values())
        checks_list.sort(key=lambda c: (c["finding"] is None, c["id"]))
        checks_list = checks_list[:max_checks]

        return {
            "hypotheses": ranked,
            "checks": checks_list,
            "files_inspected": files_seen[:max_files],
            "last_event_type": last_type,
            "total_events": total,
        }

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _save_meta(self, meta: RunMeta) -> None:
        _atomic_write(
            self.meta_path(meta.run_id),
            json.dumps(asdict(meta), ensure_ascii=False, indent=2, default=str),
        )

    def _append_run_to_session(self, session_id: str, run_id: str) -> None:
        session = self.load_session(session_id)
        if run_id in session.get("run_ids", []):
            return
        session["run_ids"] = session.get("run_ids", []) + [run_id]
        session["updated_at"] = _now_iso()
        session.setdefault("created_at", _now_iso())
        session.setdefault("session_id", session_id)
        session.setdefault("pinned", False)
        session.setdefault("title", None)
        _atomic_write(
            self.session_path(session_id),
            json.dumps(session, ensure_ascii=False, indent=2),
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _sanitize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Drop any secret-ish keys from the stored config, defensive belt."""
    out = {}
    for k, v in config.items():
        if any(bad in k.lower() for bad in ("token", "key", "secret", "password")):
            continue
        out[k] = v
    return out


def _timestamp_sort_value(ts: str) -> float:
    """Parse an ISO timestamp into a sortable float. 0 if unparseable."""
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


# --------------------------------------------------------------------------- #
# Process-wide singleton
# --------------------------------------------------------------------------- #

_STORE: RunStore | None = None


def get_store() -> RunStore:
    global _STORE
    if _STORE is None:
        _STORE = RunStore()
    return _STORE
