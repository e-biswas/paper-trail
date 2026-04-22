import { motion } from "framer-motion"
import {
  CircleAlert,
  Sparkles,
  Telescope,
  CircleHelp,
  FileSearch,
  ShieldCheck,
  Loader2,
} from "lucide-react"
import type { AssistantTurn } from "../../state/chatStore"
import { MODEL_LABEL, type ModelId, PHASE_LABEL } from "../../types"
import { HypothesisBoard } from "../run/HypothesisBoard"
import { ToolStream } from "../run/ToolStream"
import { MetricDelta } from "../run/MetricDelta"
import { Dossier } from "../run/Dossier"
import { PRCard } from "../run/PRCard"
import { QuickCheckVerdict } from "../run/QuickCheckVerdict"
import { ValidityReport } from "../run/ValidityReport"
import { ArtifactButtons } from "../run/ArtifactButtons"
import { PhaseTimeline } from "../run/PhaseTimeline"
import { Collapsible } from "../ui/Collapsible"
import { Badge } from "../ui/Badge"
import { cn } from "../../lib/cn"

interface Props {
  turn: AssistantTurn
  onValidate?: (run_id: string) => void
}

const MODE_LABEL: Record<AssistantTurn["mode"], string> = {
  investigate: "Deep Investigation",
  check: "Quick Check",
}

// Raw `aborted.reason` codes emitted by the backend → human-readable label
// for the amber "Aborted" banner. Keep the raw code visible in small text
// alongside so the UI stays forensics-friendly for power users.
const ABORT_REASON_LABEL: Record<string, string> = {
  turn_cap: "Ran out of turn budget before reaching a verdict",
  no_metric_delta: "The fix didn't change the metric — not declaring success",
  agent_requested: "Agent requested to stop",
  patch_invalid: "Proposed patch didn't apply cleanly",
  error: "Stopped due to an error",
  user_abort: "You stopped this run",
  cancelled: "Run was cancelled",
  source_exhausted_without_end: "Run ended without a final result",
}

function LivePhasePill({ phase }: { phase: string }) {
  const label = PHASE_LABEL[phase as keyof typeof PHASE_LABEL] ?? phase
  return (
    <motion.span
      animate={{ opacity: [0.6, 1, 0.6] }}
      transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
      className="inline-flex items-center gap-1 rounded-md border border-status-checking/40 bg-status-checking/10 px-1.5 py-0.5 text-[10px] font-medium text-status-checking"
    >
      <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-status-checking" />
      {label}
    </motion.span>
  )
}

function StatusBadge({ status }: { status: AssistantTurn["run_state"]["status"] }) {
  if (status === "running")
    return (
      <Badge tone="checking">
        <span className="inline-flex items-center gap-1">
          <Loader2 size={9} className="animate-spin" />
          running
        </span>
      </Badge>
    )
  if (status === "success")
    return <Badge tone="confirmed">done</Badge>
  if (status === "aborted")
    return <Badge tone="unclear">aborted</Badge>
  if (status === "error")
    return <Badge tone="refuted">error</Badge>
  return <Badge tone="pending">connecting</Badge>
}

export function AssistantMessage({ turn, onValidate }: Props) {
  const s = turn.run_state
  const hypos = s.hypothesisOrder.map((id) => s.hypotheses[id]).filter(Boolean)
  const tools = s.toolCallOrder.map((id) => s.toolCalls[id]).filter(Boolean)

  const showValidateControls =
    turn.mode === "investigate" &&
    s.status === "success" &&
    (s.verdict != null || s.aborted != null)

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex gap-3"
    >
      {/* Avatar */}
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-status-checking/20 text-status-checking">
        {turn.mode === "investigate" ? <Telescope size={14} /> : <CircleHelp size={14} />}
      </div>

      {/* Message body */}
      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-medium text-fg">Paper Trail</span>
          <span className="text-muted-fg">· {MODE_LABEL[turn.mode]}</span>
          {s.model && (
            <span className="text-[10px] text-muted-fg">
              · {MODEL_LABEL[s.model as ModelId] ?? s.model}
            </span>
          )}
          <StatusBadge status={s.status} />
          {s.status === "running" && s.currentPhase && (
            <LivePhasePill phase={s.currentPhase} />
          )}
          {s.status === "running" && s.cost_usd > 0 && (
            <span className="text-[10px] tabular-nums text-muted-fg">
              · ${s.cost_usd.toFixed(4)}
            </span>
          )}
        </div>

        {/* Errors */}
        {s.errors.length > 0 && (
          <div className="flex items-start gap-2 rounded-md border border-status-refuted/40 bg-status-refuted/10 px-3 py-2 text-sm">
            <CircleAlert size={14} className="mt-0.5 shrink-0 text-status-refuted" />
            <div>
              {s.errors.map((e, i) => (
                <div key={i}>
                  <span className="font-mono text-xs">{e.code}</span> — {e.message}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Aborted */}
        {s.aborted && (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-amber-400">Aborted</span>
              <span className="rounded-sm bg-amber-500/15 px-1.5 py-0.5 font-mono text-[10px] text-amber-300">
                {s.aborted.reason}
              </span>
            </div>
            <div className="mt-1 text-fg">
              {ABORT_REASON_LABEL[s.aborted.reason] ?? s.aborted.reason}
            </div>
            {s.aborted.detail && (
              <div className="mt-1 text-xs text-muted-fg">{s.aborted.detail}</div>
            )}
            {s.aborted.reason === "turn_cap" && (
              <div className="mt-2 text-xs text-muted-fg">
                Tip: re-run as a narrower Quick Check, or raise the budget via
                <code className="mx-1 rounded bg-muted/40 px-1 font-mono text-[10px]">
                  max_budget_usd
                </code>
                in the advanced config.
              </div>
            )}
          </div>
        )}

        {/* Quick Check result */}
        {turn.mode === "check" && s.quickCheckVerdict && (
          <QuickCheckVerdict verdict={s.quickCheckVerdict} />
        )}

        {/* Deep Investigation components */}
        {turn.mode === "investigate" && (
          <>
            {/* Paper context indicator */}
            {s.claim && !Object.keys(s.dossier).length && (
              <div className="flex items-start gap-2 rounded-md border border-border bg-card/40 px-3 py-2 text-sm">
                <FileSearch size={14} className="mt-0.5 shrink-0 text-muted-fg" />
                <div className="min-w-0 flex-1 italic text-muted-fg">{s.claim}</div>
              </div>
            )}

            {/* Hypothesis board */}
            {hypos.length > 0 && (
              <Collapsible
                title={
                  <span className="flex items-center gap-1.5">
                    <Sparkles size={12} className="text-status-checking" />
                    Hypotheses
                  </span>
                }
                subtitle={`${hypos.length} ranked`}
                badge={
                  s.verdict ? <Badge tone="verdict">🏆 verdict</Badge> : undefined
                }
                defaultOpen
              >
                <HypothesisBoard hypotheses={hypos} />
              </Collapsible>
            )}

            {/* Tool stream */}
            <Collapsible
              title="Tool activity"
              subtitle={`${tools.length} call${tools.length === 1 ? "" : "s"}`}
              defaultOpen={false}
            >
              <ToolStream toolCalls={tools} />
            </Collapsible>

            {/* Metric deltas */}
            {s.metricDeltas.length > 0 && <MetricDelta deltas={s.metricDeltas} />}

            {/* Dossier (only once sections start arriving) */}
            {(Object.keys(s.dossier).length > 0 || s.verdict) && (
              <Dossier sections={s.dossier} claim={s.claim} />
            )}

            {/* PR card */}
            {s.prOpened && <PRCard pr={s.prOpened} />}

            {/* Validity report — on-demand */}
            {s.validityReport && <ValidityReport report={s.validityReport} />}

            {/* Validity error */}
            {s.validityStatus === "error" && s.validityError && (
              <div className="flex items-start gap-2 rounded-md border border-status-refuted/40 bg-status-refuted/10 px-3 py-2 text-xs">
                <CircleAlert size={12} className="mt-0.5 shrink-0 text-status-refuted" />
                <div>
                  <span className="font-semibold">Validator failed:</span>{" "}
                  {s.validityError}
                </div>
              </div>
            )}

            {/* Validate button */}
            {showValidateControls && !s.validityReport && (
              <button
                type="button"
                disabled={s.validityStatus === "running" || !onValidate || !s.run_id}
                onClick={() => s.run_id && onValidate?.(s.run_id)}
                className={cn(
                  "inline-flex items-center gap-1.5 self-start rounded-md border border-border bg-card/60 px-3 py-1.5 text-xs",
                  "hover:bg-accent/50 disabled:cursor-not-allowed disabled:opacity-60",
                )}
                title="Have a second agent audit this run's evidence, reasoning, and fix"
              >
                {s.validityStatus === "running" ? (
                  <>
                    <Loader2 size={12} className="animate-spin" />
                    validator auditing…
                  </>
                ) : (
                  <>
                    <ShieldCheck size={12} className="text-status-checking" />
                    Run validator (~$0.05, 10–15s)
                  </>
                )}
              </button>
            )}
          </>
        )}

        {/* Phase timeline — live during run, summary after */}
        {(s.status === "running" ||
          Object.keys(s.phaseTimings).length > 0 ||
          s.currentPhase) && (
          <div className="pt-1">
            <PhaseTimeline
              phaseTimings={s.phaseTimings}
              currentPhase={s.currentPhase}
              currentPhaseStartedAt={s.currentPhaseStartedAt}
              status={s.status}
              liveMode={s.status === "running"}
            />
          </div>
        )}

        {/* Footer: artifact buttons + cost */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-2">
          <ArtifactButtons runState={s} />
          {s.status === "success" && (
            <div className="text-xs tabular-nums text-muted-fg">
              {s.total_turns > 0 && <span>{s.total_turns} turns · </span>}
              {s.duration_ms > 0 && (
                <span>{(s.duration_ms / 1000).toFixed(1)}s · </span>
              )}
              <span className={cn(s.cost_usd >= 1 ? "text-fg" : "")}>
                ${s.cost_usd.toFixed(4)}
              </span>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  )
}
