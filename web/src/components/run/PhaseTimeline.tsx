import { useEffect, useState } from "react"
import { motion } from "framer-motion"
import {
  BookText,
  Sparkles,
  ClipboardCheck,
  Wrench,
  ScrollText,
  GitPullRequest,
  type LucideIcon,
} from "lucide-react"
import type { PhaseName } from "../../types"
import { PHASE_LABEL } from "../../types"
import { cn } from "../../lib/cn"

const PHASE_ORDER: PhaseName[] = [
  "paper_ingest",
  "hypotheses",
  "checks",
  "verify",
  "dossier",
  "pr",
]

const PHASE_ICON: Record<PhaseName, LucideIcon> = {
  paper_ingest: BookText,
  hypotheses: Sparkles,
  checks: ClipboardCheck,
  verify: Wrench,
  dossier: ScrollText,
  pr: GitPullRequest,
}

interface Props {
  phaseTimings: Partial<Record<PhaseName, number>>
  currentPhase: PhaseName | null
  currentPhaseStartedAt: number | null
  status: "connecting" | "running" | "success" | "error" | "aborted"
  /** If true, render the compact finished-timings strip; otherwise show the live ticker. */
  liveMode: boolean
}

/** Inline timeline strip: each phase gets an icon + duration + subtle bar.
 *
 * While the run is live, the current phase is highlighted and its elapsed
 * time counts up. Once finished, the whole timeline is a read-only summary.
 */
export function PhaseTimeline({
  phaseTimings,
  currentPhase,
  currentPhaseStartedAt,
  status,
  liveMode,
}: Props) {
  // Only render phases that have fired or are firing — keeps the strip honest.
  const visible = PHASE_ORDER.filter((p) => phaseTimings[p] != null || p === currentPhase)
  if (visible.length === 0) return null

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-fg",
        !liveMode && "tabular-nums",
      )}
    >
      {visible.map((phase) => {
        const isCurrent = phase === currentPhase && status === "running"
        const finishedMs = phaseTimings[phase]
        return (
          <PhaseChip
            key={phase}
            phase={phase}
            isCurrent={isCurrent}
            finishedMs={finishedMs}
            currentPhaseStartedAt={isCurrent ? currentPhaseStartedAt : null}
          />
        )
      })}
    </div>
  )
}

function PhaseChip({
  phase,
  isCurrent,
  finishedMs,
  currentPhaseStartedAt,
}: {
  phase: PhaseName
  isCurrent: boolean
  finishedMs: number | undefined
  currentPhaseStartedAt: number | null
}) {
  const Icon = PHASE_ICON[phase]
  const label = PHASE_LABEL[phase]

  // Live-tick the current phase's elapsed time.
  const [liveMs, setLiveMs] = useState<number>(() =>
    currentPhaseStartedAt != null ? Date.now() - currentPhaseStartedAt : 0,
  )
  useEffect(() => {
    if (!isCurrent || currentPhaseStartedAt == null) return
    const id = window.setInterval(() => {
      setLiveMs(Date.now() - currentPhaseStartedAt)
    }, 250)
    return () => window.clearInterval(id)
  }, [isCurrent, currentPhaseStartedAt])

  const shownMs = isCurrent ? liveMs : finishedMs ?? 0
  const durationStr = _fmtMs(shownMs)

  return (
    <motion.span
      initial={{ opacity: 0, y: 2 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5",
        isCurrent
          ? "border-status-checking/50 bg-status-checking/10 text-status-checking"
          : finishedMs != null
          ? "border-border/60 bg-card/40"
          : "border-border/30 bg-card/20 opacity-60",
      )}
    >
      {isCurrent ? (
        <motion.span
          animate={{ scale: [1, 1.15, 1], opacity: [1, 0.6, 1] }}
          transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
          className="inline-flex"
        >
          <Icon size={10} />
        </motion.span>
      ) : (
        <Icon size={10} />
      )}
      <span className="font-medium">{label}</span>
      <span>{durationStr}</span>
    </motion.span>
  )
}

function _fmtMs(ms: number): string {
  if (ms < 1000) return `${Math.max(0, ms).toFixed(0)}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const r = Math.round(s - m * 60)
  return `${m}m${r}s`
}
