import { useEffect, useMemo, useState } from "react"
import {
  MessageSquarePlus,
  GitPullRequest,
  FlaskConical,
  FileSearch,
  Pin,
  PinOff,
  Loader2,
  ShieldCheck,
  Trash2,
  Check,
  X,
} from "lucide-react"
import type { ChatTurn } from "../../state/chatStore"
import type { SessionList, SessionSummary } from "../../types"
import { cn } from "../../lib/cn"

interface Props {
  sessionId: string
  turns: ChatTurn[]
  isRunning: boolean
  onNewSession: () => void
  onLoadSession: (session_id: string) => void
  onDeleteSession?: (session_id: string) => void | Promise<void>
}

/** All sessions grouped by pinned/recent. Current session highlighted. */
export function Sidebar({
  sessionId,
  turns,
  isRunning,
  onNewSession,
  onLoadSession,
  onDeleteSession,
}: Props) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [usage, setUsage] = useState<{ total: number; n_runs: number } | null>(null)
  const [busyPin, setBusyPin] = useState<string | null>(null)
  const [busyDelete, setBusyDelete] = useState<string | null>(null)

  async function refresh() {
    try {
      const [g, l] = await Promise.all([
        fetch("/usage").then((r) => r.json()),
        fetch("/sessions").then((r) => r.json() as Promise<SessionList>),
      ])
      setUsage({ total: g.total_cost_usd ?? 0, n_runs: g.n_runs ?? 0 })
      setSessions(l.sessions ?? [])
    } catch {
      // backend might not be up yet
    }
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [sessionId, turns.length])

  async function togglePin(sid: string, currentlyPinned: boolean) {
    setBusyPin(sid)
    try {
      await fetch(`/sessions/${sid}/pin?pinned=${!currentlyPinned}`, {
        method: "POST",
      })
      await refresh()
    } catch {
      // best-effort; refresh() will pull truth next tick
    } finally {
      setBusyPin(null)
    }
  }

  async function handleDelete(sid: string) {
    if (!onDeleteSession) return
    setBusyDelete(sid)
    try {
      await onDeleteSession(sid)
      await refresh()
    } finally {
      setBusyDelete(null)
    }
  }

  // Build a pseudo "current" session summary from the live turns so the sidebar
  // still shows the run-in-progress even before its events are persisted.
  const liveSessionFromTurns = useMemo(() => {
    const assistantTurns = turns.filter((t) => t.kind === "assistant")
    if (assistantTurns.length === 0) return null
    return assistantTurns
  }, [turns])

  const { pinned, recent } = useMemo(() => {
    const p: SessionSummary[] = []
    const r: SessionSummary[] = []
    for (const s of sessions) {
      if (s.pinned) p.push(s)
      else r.push(s)
    }
    return { pinned: p, recent: r }
  }, [sessions])

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-card/30">
      <div className="flex items-center justify-between border-b border-border px-3 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <span>Paper Trail</span>
        </div>
      </div>

      <div className="px-3 py-3">
        <button
          type="button"
          onClick={onNewSession}
          disabled={isRunning}
          className={cn(
            "flex w-full items-center gap-2 rounded-md border border-border bg-accent/40 px-2.5 py-1.5 text-sm",
            "hover:bg-accent/70 disabled:cursor-not-allowed disabled:opacity-60",
          )}
          title={isRunning ? "Wait for the current run to finish" : "Start a new session"}
        >
          <MessageSquarePlus size={14} />
          New session
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {/* Live current session — always visible at the top if it has runs */}
        {liveSessionFromTurns && (
          <>
            <div className="mb-1 px-1 text-[10px] uppercase tracking-wider text-muted-fg">
              Current session
            </div>
            <div className="mb-3 space-y-1">
              {turns
                .filter((t) => t.kind === "assistant")
                .map((t, i) => {
                  if (t.kind !== "assistant") return null
                  const s = t.run_state
                  return (
                    <div
                      key={t.id}
                      className={cn(
                        "rounded-md border border-transparent px-2 py-1.5 text-xs",
                        "hover:border-border hover:bg-accent/30",
                      )}
                    >
                      <div className="flex items-center gap-1.5">
                        {t.mode === "investigate" ? (
                          <FlaskConical size={11} className="text-status-checking" />
                        ) : (
                          <FileSearch size={11} className="text-muted-fg" />
                        )}
                        <span className="font-medium">
                          {t.mode === "investigate"
                            ? `Investigation #${i + 1}`
                            : `Check #${i + 1}`}
                        </span>
                        {s.status === "running" && (
                          <Loader2 size={10} className="animate-spin text-status-checking" />
                        )}
                      </div>
                      <div className="mt-0.5 truncate text-[10px] text-muted-fg">
                        {s.verdict?.summary ||
                          s.quickCheckVerdict?.notes ||
                          s.claim ||
                          s.status}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-fg">
                        {s.prOpened && <GitPullRequest size={10} className="text-status-verdict" />}
                        {s.validityReport && (
                          <ShieldCheck size={10} className="text-status-checking" />
                        )}
                        <span className="tabular-nums">${s.cost_usd.toFixed(3)}</span>
                        {s.duration_ms > 0 && (
                          <span className="tabular-nums">
                            · {(s.duration_ms / 1000).toFixed(1)}s
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
            </div>
          </>
        )}

        {pinned.length > 0 && (
          <SessionGroup
            label="Pinned"
            sessions={pinned}
            activeId={sessionId}
            busyPin={busyPin}
            busyDelete={busyDelete}
            onOpen={onLoadSession}
            onPin={togglePin}
            onDelete={onDeleteSession ? handleDelete : undefined}
            disabled={isRunning}
          />
        )}

        <SessionGroup
          label="Recent"
          sessions={recent.filter((s) => s.session_id !== sessionId)}
          activeId={sessionId}
          busyPin={busyPin}
          busyDelete={busyDelete}
          onOpen={onLoadSession}
          onPin={togglePin}
          onDelete={onDeleteSession ? handleDelete : undefined}
          disabled={isRunning}
          emptyHint={
            recent.length === 0 && pinned.length === 0
              ? "No past sessions yet. Send a message to start."
              : undefined
          }
        />
      </div>

      <div className="border-t border-border px-3 py-2 text-[10px] text-muted-fg">
        {usage && (
          <div className="flex justify-between">
            <span>all time</span>
            <span className="tabular-nums">
              ${usage.total.toFixed(4)} · {usage.n_runs} runs
            </span>
          </div>
        )}
      </div>
    </aside>
  )
}

function SessionGroup({
  label,
  sessions,
  activeId,
  busyPin,
  busyDelete,
  onOpen,
  onPin,
  onDelete,
  disabled,
  emptyHint,
}: {
  label: string
  sessions: SessionSummary[]
  activeId: string
  busyPin: string | null
  busyDelete: string | null
  onOpen: (sid: string) => void
  onPin: (sid: string, currentlyPinned: boolean) => void
  onDelete?: (sid: string) => void | Promise<void>
  disabled: boolean
  emptyHint?: string
}) {
  return (
    <div className="mb-3">
      <div className="mb-1 px-1 text-[10px] uppercase tracking-wider text-muted-fg">
        {label}
      </div>
      {sessions.length === 0 ? (
        emptyHint ? (
          <div className="rounded-md px-2 py-1.5 text-[11px] text-muted-fg">
            {emptyHint}
          </div>
        ) : null
      ) : (
        <div className="space-y-1">
          {sessions.map((s) => (
            <SessionRow
              key={s.session_id}
              session={s}
              active={s.session_id === activeId}
              busyPin={busyPin === s.session_id}
              busyDelete={busyDelete === s.session_id}
              onOpen={() => onOpen(s.session_id)}
              onPin={() => onPin(s.session_id, !!s.pinned)}
              onDelete={onDelete ? () => onDelete(s.session_id) : undefined}
              disabled={disabled}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function SessionRow({
  session,
  active,
  busyPin,
  busyDelete,
  onOpen,
  onPin,
  onDelete,
  disabled,
}: {
  session: SessionSummary
  active: boolean
  busyPin: boolean
  busyDelete: boolean
  onOpen: () => void
  onPin: () => void
  onDelete?: () => void | Promise<void>
  disabled: boolean
}) {
  // Inline two-step confirm: first trash-click flips the row into "Delete?"
  // mode with ✓ / ✗ buttons. No modal — keeps the sidebar aesthetic intact.
  const [confirmDelete, setConfirmDelete] = useState(false)

  const lastRun = session.runs[session.runs.length - 1]
  const title =
    session.title ||
    (lastRun?.verdict_summary && lastRun.verdict_summary.length < 80
      ? lastRun.verdict_summary
      : lastRun?.first_user_text) ||
    lastRun?.paper_url ||
    lastRun?.repo_path ||
    "Untitled session"

  const hasPR = session.runs.some((r) => !!r.pr_url)
  const hasValidity = session.runs.some((r) => !!r.validity_overall)
  const lastIsInvestigate = lastRun?.mode === "investigate"

  return (
    <div
      className={cn(
        "group flex items-start gap-1.5 rounded-md border px-2 py-1.5 text-xs",
        active
          ? "border-status-checking/60 bg-status-checking/10"
          : "border-transparent hover:border-border hover:bg-accent/30",
        confirmDelete && "border-status-refuted/50 bg-status-refuted/5",
      )}
    >
      <button
        type="button"
        onClick={onOpen}
        disabled={disabled || confirmDelete}
        className="flex min-w-0 flex-1 flex-col items-start gap-0.5 text-left disabled:cursor-not-allowed disabled:opacity-60"
        title={title}
      >
        <div className="flex w-full items-center gap-1.5">
          {lastIsInvestigate ? (
            <FlaskConical size={11} className="shrink-0 text-status-checking" />
          ) : (
            <FileSearch size={11} className="shrink-0 text-muted-fg" />
          )}
          <span className="truncate font-medium">{title}</span>
        </div>
        <div className="flex w-full items-center gap-1.5 text-[10px] text-muted-fg">
          {hasPR && <GitPullRequest size={10} className="text-status-verdict" />}
          {hasValidity && <ShieldCheck size={10} className="text-status-checking" />}
          <span className="tabular-nums">
            {session.n_runs} run{session.n_runs === 1 ? "" : "s"}
          </span>
          <span className="tabular-nums">· ${session.total_cost_usd.toFixed(3)}</span>
        </div>
      </button>

      {confirmDelete ? (
        <div
          className="flex shrink-0 items-center gap-0.5"
          role="alertdialog"
          aria-label={`Delete ${title}?`}
        >
          <span className="mr-1 text-[10px] text-status-refuted">Delete?</span>
          <button
            type="button"
            onClick={async (e) => {
              e.stopPropagation()
              await onDelete?.()
              setConfirmDelete(false)
            }}
            disabled={busyDelete}
            className="rounded p-1 text-status-refuted hover:bg-status-refuted/15 disabled:opacity-60"
            title={`Delete ${session.n_runs} run${session.n_runs === 1 ? "" : "s"} · $${session.total_cost_usd.toFixed(3)}. Cannot be undone.`}
          >
            {busyDelete ? (
              <Loader2 size={11} className="animate-spin" />
            ) : (
              <Check size={11} />
            )}
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setConfirmDelete(false)
            }}
            className="rounded p-1 text-muted-fg hover:bg-accent/50 hover:text-fg"
            title="Cancel"
          >
            <X size={11} />
          </button>
        </div>
      ) : (
        <>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onPin()
            }}
            disabled={busyPin}
            className={cn(
              "shrink-0 rounded p-1 text-muted-fg",
              "hover:bg-accent/50 hover:text-fg",
              session.pinned
                ? "opacity-100 text-status-verdict"
                : "opacity-0 group-hover:opacity-100",
              busyPin && "opacity-100",
            )}
            title={session.pinned ? "Unpin" : "Pin to top"}
          >
            {busyPin ? (
              <Loader2 size={11} className="animate-spin" />
            ) : session.pinned ? (
              <PinOff size={11} />
            ) : (
              <Pin size={11} />
            )}
          </button>

          {onDelete && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setConfirmDelete(true)
              }}
              className={cn(
                "shrink-0 rounded p-1 text-muted-fg",
                "hover:bg-status-refuted/15 hover:text-status-refuted",
                "opacity-0 group-hover:opacity-100",
              )}
              title="Delete chat"
            >
              <Trash2 size={11} />
            </button>
          )}
        </>
      )}
    </div>
  )
}
