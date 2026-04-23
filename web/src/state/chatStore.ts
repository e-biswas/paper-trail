// Conversation state: the chat thread that assembles runs into turns.
//
// Each user message spawns ONE run. The assistant "reply" is a rich block
// rendered from that run's RunState. Prior turns stay visible for continuity.

import { useEffect, useRef, useState } from "react"
import { applyEnvelope, emptyRunState, type RunState } from "./runState"
import type { Envelope, Mode, ModelId, ValidityReportData, SessionSummary } from "../types"

export interface UserTurn {
  kind: "user"
  id: string
  mode: Mode
  text: string
  ts: string
  model?: ModelId
  config: { paper_url?: string; repo_path?: string; repo_slug?: string; question?: string }
}

export interface AssistantTurn {
  kind: "assistant"
  id: string                 // run_id
  mode: Mode
  run_state: RunState
}

export type ChatTurn = UserTurn | AssistantTurn

export interface StartRunInput {
  mode: Mode
  text: string
  paper_url?: string
  repo_path?: string
  repo_slug?: string | null
  model?: ModelId
  /** Deep Investigation only. When false, the agent stops after the Dossier
   *  blocks; the user opens the PR manually via a button in the assistant
   *  message. Default true (hackathon demo path). */
  auto_pr?: boolean
}

export interface ChatStore {
  turns: ChatTurn[]
  sessionId: string
  isRunning: boolean
  error: string | null
  startRun: (input: StartRunInput) => void
  stopRun: () => void
  newSession: () => void
  loadSession: (session_id: string) => Promise<void>
  validateRun: (run_id: string) => Promise<void>
  setSelectedHypothesis: (run_id: string, hypothesis_id: string | null) => void
  pushPr: (run_id: string) => Promise<void>
  deleteSession: (session_id: string) => Promise<void>
}


/** Generate a short, friendly run id. */
function makeRunId(): string {
  return "run-" + Math.random().toString(36).slice(2, 10)
}

/** Generate a session id persisted per-browser-tab. */
function makeSessionId(): string {
  return "s-" + Math.random().toString(36).slice(2, 10) + "-" + Date.now().toString(36)
}

const STORAGE_KEY = "repro.sessionId"


export function useChatStore(): ChatStore {
  const [sessionId, setSessionId] = useState<string>(() => {
    const existing = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null
    if (existing) return existing
    const fresh = makeSessionId()
    if (typeof window !== "undefined") localStorage.setItem(STORAGE_KEY, fresh)
    return fresh
  })
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [isRunning, setIsRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)

  // Cleanup any open socket on unmount.
  useEffect(() => {
    return () => wsRef.current?.close()
  }, [])

  function newSession() {
    const fresh = makeSessionId()
    localStorage.setItem(STORAGE_KEY, fresh)
    setSessionId(fresh)
    setTurns([])
    setError(null)
  }

  /** Send a `stop` frame on the live WebSocket. Backend cancels the agent
   * task and emits a terminal `session_end` with `stop_reason: "user_abort"`. */
  function stopRun() {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    try {
      ws.send(JSON.stringify({ type: "stop" }))
    } catch (err) {
      console.warn("stop frame send failed", err)
    }
  }

  function startRun(input: StartRunInput) {
    if (isRunning) return
    setError(null)

    const run_id = makeRunId()
    const endpoint = input.mode === "investigate" ? "/ws/investigate" : "/ws/check"
    const url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + endpoint

    // Build the start-frame config.
    const config: Record<string, unknown> = {
      session_id: sessionId,
      max_budget_usd: input.mode === "investigate" ? 5.0 : 1.0,
      // Always capture what the user typed so the sidebar can label the run.
      // In Quick Check mode this is the same string as `question` — the
      // backend just stores it alongside.
      user_prompt: input.text,
    }
    if (input.model) config.model = input.model
    if (input.mode === "investigate") {
      if (input.paper_url) config.paper_url = input.paper_url
      if (input.repo_path) config.repo_path = input.repo_path
      if (input.repo_slug) config.repo_slug = input.repo_slug
      // Default true (hackathon demo path). The InputRow sends an explicit
      // boolean when the user toggles the pill so this only matters for
      // programmatic callers that forget to set it.
      config.auto_pr = input.auto_pr ?? true
    } else {
      config.question = input.text
      if (input.repo_path) config.repo_path = input.repo_path
    }

    // User bubble goes in first.
    const userTurn: UserTurn = {
      kind: "user",
      id: `u-${run_id}`,
      mode: input.mode,
      text: input.text,
      ts: new Date().toISOString(),
      model: input.model,
      config: {
        paper_url: input.paper_url,
        repo_path: input.repo_path,
        repo_slug: input.repo_slug ?? undefined,
        question: input.mode === "check" ? input.text : undefined,
      },
    }
    const assistantTurn: AssistantTurn = {
      kind: "assistant",
      id: run_id,
      mode: input.mode,
      run_state: {
        ...emptyRunState(),
        run_id,
        session_id: sessionId,
        mode: input.mode,
        model: input.model ?? null,
      },
    }
    setTurns((ts) => [...ts, userTurn, assistantTurn])
    setIsRunning(true)

    // Open the socket.
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.addEventListener("open", () => {
      ws.send(JSON.stringify({ type: "start", run_id, config }))
    })

    ws.addEventListener("message", (ev) => {
      let env: Envelope
      try {
        env = JSON.parse(ev.data as string)
      } catch {
        return
      }
      setTurns((ts) =>
        ts.map((t) =>
          t.kind === "assistant" && t.id === run_id
            ? { ...t, run_state: applyEnvelope(t.run_state, env) }
            : t,
        ),
      )
      if (env.type === "session_end" || env.type === "error") {
        ws.close()
      }
    })

    ws.addEventListener("close", () => {
      setIsRunning(false)
      wsRef.current = null
    })

    ws.addEventListener("error", (ev) => {
      console.error("ws error", ev)
      setError("WebSocket error — is the backend running on port 8080?")
      setIsRunning(false)
    })
  }

  /** Patch one assistant turn's run_state without disturbing the others. */
  function _patchTurn(run_id: string, patch: (s: RunState) => RunState) {
    setTurns((ts) =>
      ts.map((t) =>
        t.kind === "assistant" && t.id === run_id
          ? { ...t, run_state: patch(t.run_state) }
          : t,
      ),
    )
  }

  /** Load a past session from the backend and animate its runs onto the chat.
   *
   * Each past run's events are replayed through the reducer on a short stagger
   * so the hypothesis board / tool stream / dossier reconstruct visibly.
   * The user can keep chatting in the same session afterward — server-side
   * session_id memory is preserved.
   */
  async function loadSession(session_id: string) {
    if (isRunning) {
      // Don't clobber a live run.
      return
    }
    setError(null)
    try {
      // Fetch session overview (metadata + per-run summaries).
      const resSummary = await fetch(`/sessions/${session_id}`)
      if (!resSummary.ok) throw new Error(`session not found: ${resSummary.status}`)
      const summary = (await resSummary.json()) as SessionSummary

      if (typeof window !== "undefined") {
        localStorage.setItem(STORAGE_KEY, session_id)
      }
      setSessionId(session_id)

      // Sort runs chronologically just in case.
      const runs = [...summary.runs].sort((a, b) =>
        (a.created_at ?? "").localeCompare(b.created_at ?? ""),
      )

      // Build initial (skeleton) turns from meta so sidebar selection is instant.
      const seedTurns: ChatTurn[] = []
      for (const r of runs) {
        const userText =
          (typeof r.first_user_text === "string" && r.first_user_text) ||
          r.verdict_summary ||
          (r.mode === "investigate"
            ? "Investigate this repo"
            : "Quick check")
        seedTurns.push({
          kind: "user",
          id: `u-${r.run_id}`,
          mode: r.mode,
          text: userText,
          ts: r.created_at,
          model: (r.model as ModelId | undefined) ?? undefined,
          config: {
            paper_url: r.paper_url ?? undefined,
            repo_path: r.repo_path ?? undefined,
            repo_slug: r.repo_slug ?? undefined,
            question: r.mode === "check" ? userText : undefined,
          },
        })
        seedTurns.push({
          kind: "assistant",
          id: r.run_id,
          mode: r.mode,
          run_state: {
            ...emptyRunState(),
            run_id: r.run_id,
            session_id,
            mode: r.mode,
            model: (r.model as ModelId | null) ?? null,
            status: "connecting",
            isReplay: true,
          },
        })
      }
      setTurns(seedTurns)

      // Replay each run's events.jsonl through the reducer, staggered so the
      // UI animates. Runs replay in series so the cost/duration stats arrive
      // roughly in the original order.
      for (const r of runs) {
        try {
          const evRes = await fetch(`/runs/${r.run_id}/events.jsonl`)
          if (!evRes.ok) continue
          const text = await evRes.text()
          const lines = text.split("\n").filter((l) => l.trim().length > 0)
          // Fast-replay: stagger by a few ms per event (not real wall-clock time).
          for (const line of lines) {
            let env: Envelope
            try {
              env = JSON.parse(line)
            } catch {
              continue
            }
            _patchTurn(r.run_id, (s) => applyEnvelope(s, env))
            // Tiny delay so framer-motion animations have a chance to register.
            await _sleep(4)
          }
          // After the stream, if the run had a cached validity_report in meta,
          // reflect it in the UI without re-triggering the backend.
          if (r.validity_overall) {
            try {
              const valRes = await fetch(`/runs/${r.run_id}/validate`, { method: "POST" })
              if (valRes.ok) {
                const body = (await valRes.json()) as ValidityReportData
                _patchTurn(r.run_id, (s) => ({
                  ...s,
                  validityStatus: "ready",
                  validityReport: body,
                }))
              }
            } catch {
              // ignore — not critical
            }
          }
        } catch (exc) {
          console.warn("replay failed for run", r.run_id, exc)
        }
      }
    } catch (exc: unknown) {
      const msg = exc instanceof Error ? exc.message : String(exc)
      setError(`Could not load session: ${msg}`)
    }
  }

  function _sleep(ms: number) {
    return new Promise<void>((resolve) => setTimeout(resolve, ms))
  }

  async function validateRun(run_id: string) {
    // Mark the turn as running; no-op if not found.
    _patchTurn(run_id, (s) => ({ ...s, validityStatus: "running", validityError: null }))
    try {
      const res = await fetch(`/runs/${run_id}/validate`, { method: "POST" })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(`${res.status}: ${text.slice(0, 200)}`)
      }
      const body = (await res.json()) as ValidityReportData
      _patchTurn(run_id, (s) => ({
        ...s,
        validityStatus: "ready",
        validityReport: body,
        validityError: null,
      }))
    } catch (exc: unknown) {
      const msg = exc instanceof Error ? exc.message : String(exc)
      _patchTurn(run_id, (s) => ({
        ...s,
        validityStatus: "error",
        validityError: msg,
      }))
    }
  }

  function setSelectedHypothesis(run_id: string, hypothesis_id: string | null) {
    _patchTurn(run_id, (s) => ({
      ...s,
      // Clicking the same card twice clears the filter.
      selectedHypothesisId: s.selectedHypothesisId === hypothesis_id ? null : hypothesis_id,
    }))
  }

  /** Manually open the PR for a completed Deep Investigation whose run was
   *  started with `auto_pr=false`. Backend spawns a focused agent that
   *  forks (if needed), commits the post-fix files, and opens the PR.
   *  On success the new `pr_opened` envelope is replayed into the run's
   *  event log server-side and echoed back here so the reducer folds it in. */
  async function pushPr(run_id: string) {
    _patchTurn(run_id, (s) => ({ ...s, prPushStatus: "running", prPushError: null }))
    try {
      const res = await fetch(`/runs/${run_id}/push_pr`, { method: "POST" })
      const raw = await res.text()
      let body: unknown = null
      if (raw) {
        try { body = JSON.parse(raw) } catch { /* non-JSON body */ }
      }
      if (!res.ok) {
        const detail = (body as { detail?: string } | null)?.detail || raw.slice(0, 200) || `HTTP ${res.status}`
        throw new Error(detail)
      }
      const d = body as { url?: string; number?: number; title?: string } | null
      if (!d?.url) {
        throw new Error("server returned no PR url")
      }
      const env: Envelope = {
        type: "pr_opened",
        run_id,
        ts: new Date().toISOString(),
        seq: -1,   // server-authoritative seq lives in the persisted log
        data: { url: d.url, number: d.number ?? 0, title: d.title ?? "" },
      }
      _patchTurn(run_id, (s) => ({
        ...applyEnvelope(s, env),
        prPushStatus: "ready",
      }))
    } catch (exc: unknown) {
      const msg = exc instanceof Error ? exc.message : String(exc)
      _patchTurn(run_id, (s) => ({ ...s, prPushStatus: "error", prPushError: msg }))
    }
  }

  /** Hard-delete a session and every run it references. If `session_id`
   *  matches the currently-loaded session, we also reset to a fresh one so
   *  the UI doesn't linger on an empty / deleted id. No undo. */
  async function deleteSession(session_id: string) {
    setError(null)
    try {
      const res = await fetch(`/sessions/${session_id}`, { method: "DELETE" })
      if (!res.ok && res.status !== 404) {
        const txt = await res.text()
        throw new Error(`delete failed: ${res.status} ${txt.slice(0, 200)}`)
      }
      if (session_id === sessionId) {
        newSession()
      }
    } catch (exc: unknown) {
      const msg = exc instanceof Error ? exc.message : String(exc)
      setError(`Could not delete session: ${msg}`)
    }
  }

  return {
    turns,
    sessionId,
    isRunning,
    error,
    startRun,
    stopRun,
    newSession,
    loadSession,
    validateRun,
    setSelectedHypothesis,
    pushPr,
    deleteSession,
  }
}
