// Per-run state that an assistant chat message renders from.
//
// One chat turn = one run. The reducer builds up this state as envelopes
// arrive over the WebSocket. Components read slices of it to render
// Hypothesis Board, Tool Stream, Dossier, etc. — all inside the assistant
// message bubble.

import type {
  AbortedData,
  CheckData,
  ClaimSummaryData,
  DossierSection,
  DossierSectionData,
  Envelope,
  ErrorData,
  FindingData,
  FixAppliedData,
  HypothesisData,
  HypothesisUpdateData,
  MetricDeltaData,
  Mode,
  ModelId,
  PhaseEndData,
  PhaseName,
  PhaseStartData,
  PROpenedData,
  QuickCheckVerdictData,
  SessionEndData,
  SessionStartData,
  ToolCallData,
  ToolResultData,
  ValidityReportData,
  VerdictData,
} from "../types"

export type RunStatus =
  | "connecting"
  | "running"
  | "success"
  | "error"
  | "aborted"

export interface HypothesisItem {
  id: string
  rank: number
  name: string
  confidence: number
  reason: string
  reasonDelta?: string
  status: "pending" | "checking" | "confirmed" | "refuted" | "verdict"
  confidenceHistory: number[]
}

export interface CheckItem {
  id: string
  hypothesis_id: string
  description: string
  method?: string
  finding?: FindingData
}

export interface ToolCallItem {
  id: string
  name: string
  input: Record<string, unknown>
  output: string | null
  is_error: boolean
  duration_ms: number | null
  started_at: string
  finished_at: string | null
}

export type ValidityStatus = "idle" | "running" | "ready" | "error"

export interface RunState {
  run_id: string | null
  session_id: string | null
  mode: Mode | null
  model: ModelId | null
  status: RunStatus
  claim: string | null
  hypotheses: Record<string, HypothesisItem>
  hypothesisOrder: string[]
  checks: Record<string, CheckItem>
  checkOrder: string[]
  toolCalls: Record<string, ToolCallItem>
  toolCallOrder: string[]
  verdict: VerdictData | null
  fixApplied: FixAppliedData | null
  metricDeltas: MetricDeltaData[]
  dossier: Partial<Record<DossierSection, string>>
  prOpened: PROpenedData | null
  quickCheckVerdict: QuickCheckVerdictData | null
  aborted: AbortedData | null
  errors: ErrorData[]
  cost_usd: number
  total_turns: number
  duration_ms: number
  // Phase tracking — feeds both the live "what's happening now" indicator
  // and the post-run inline timings footer.
  phaseTimings: Partial<Record<PhaseName, number>>
  phaseOrder: PhaseName[]
  currentPhase: PhaseName | null
  currentPhaseStartedAt: number | null    // ms epoch, for live-ticker display
  // Post-run validator state (populated when the user clicks "Validate").
  validityStatus: ValidityStatus
  validityReport: ValidityReportData | null
  validityError: string | null
  // True if this run state was loaded from disk rather than streamed live.
  isReplay: boolean
}

export function emptyRunState(): RunState {
  return {
    run_id: null,
    session_id: null,
    mode: null,
    model: null,
    status: "connecting",
    claim: null,
    hypotheses: {},
    hypothesisOrder: [],
    checks: {},
    checkOrder: [],
    toolCalls: {},
    toolCallOrder: [],
    verdict: null,
    fixApplied: null,
    metricDeltas: [],
    dossier: {},
    prOpened: null,
    quickCheckVerdict: null,
    aborted: null,
    errors: [],
    cost_usd: 0,
    total_turns: 0,
    duration_ms: 0,
    phaseTimings: {},
    phaseOrder: [],
    currentPhase: null,
    currentPhaseStartedAt: null,
    validityStatus: "idle",
    validityReport: null,
    validityError: null,
    isReplay: false,
  }
}

/** Fold one envelope into run state. Idempotent-ish and defensive. */
export function applyEnvelope(state: RunState, env: Envelope): RunState {
  switch (env.type) {
    case "session_start": {
      const d = env.data as SessionStartData
      return { ...state, run_id: env.run_id, mode: d.mode, status: "running" }
    }

    case "claim_summary": {
      const d = env.data as ClaimSummaryData
      return { ...state, claim: d.claim }
    }

    case "hypothesis": {
      const d = env.data as HypothesisData
      if (state.hypotheses[d.id]) return state
      return {
        ...state,
        hypotheses: {
          ...state.hypotheses,
          [d.id]: {
            id: d.id,
            rank: d.rank,
            name: d.name,
            confidence: d.confidence,
            reason: d.reason,
            status: "pending",
            confidenceHistory: [d.confidence],
          },
        },
        hypothesisOrder: [...state.hypothesisOrder, d.id],
      }
    }

    case "hypothesis_update": {
      const d = env.data as HypothesisUpdateData
      const existing = state.hypotheses[d.id]
      if (!existing) return state
      return {
        ...state,
        hypotheses: {
          ...state.hypotheses,
          [d.id]: {
            ...existing,
            confidence: d.confidence,
            reasonDelta: d.reason_delta,
            confidenceHistory: [...existing.confidenceHistory, d.confidence],
          },
        },
      }
    }

    case "check": {
      const d = env.data as CheckData
      const hy = state.hypotheses[d.hypothesis_id]
      return {
        ...state,
        checks: { ...state.checks, [d.id]: d },
        checkOrder: [...state.checkOrder, d.id],
        hypotheses: hy
          ? {
              ...state.hypotheses,
              [d.hypothesis_id]: { ...hy, status: "checking" },
            }
          : state.hypotheses,
      }
    }

    case "finding": {
      const d = env.data as FindingData
      const check = state.checks[d.check_id]
      let hypotheses = state.hypotheses
      for (const hId of d.supports ?? []) {
        const h = hypotheses[hId]
        if (h) hypotheses = { ...hypotheses, [hId]: { ...h, status: "confirmed" } }
      }
      for (const hId of d.refutes ?? []) {
        const h = hypotheses[hId]
        if (h) hypotheses = { ...hypotheses, [hId]: { ...h, status: "refuted" } }
      }
      return {
        ...state,
        checks: check
          ? { ...state.checks, [d.check_id]: { ...check, finding: d } }
          : state.checks,
        hypotheses,
      }
    }

    case "verdict": {
      const d = env.data as VerdictData
      const winner = state.hypotheses[d.hypothesis_id]
      const hypotheses = winner
        ? {
            ...state.hypotheses,
            [d.hypothesis_id]: { ...winner, status: "verdict" as const, confidence: d.confidence },
          }
        : state.hypotheses
      return { ...state, verdict: d, hypotheses }
    }

    case "fix_applied":
      return { ...state, fixApplied: env.data as FixAppliedData }

    case "metric_delta":
      return { ...state, metricDeltas: [...state.metricDeltas, env.data as MetricDeltaData] }

    case "dossier_section": {
      const d = env.data as DossierSectionData
      return { ...state, dossier: { ...state.dossier, [d.section]: d.markdown } }
    }

    case "pr_opened":
      return { ...state, prOpened: env.data as PROpenedData }

    case "quick_check_verdict":
      return { ...state, quickCheckVerdict: env.data as QuickCheckVerdictData }

    case "tool_call": {
      const d = env.data as ToolCallData
      return {
        ...state,
        toolCalls: {
          ...state.toolCalls,
          [d.id]: {
            id: d.id,
            name: d.name,
            input: d.input,
            output: null,
            is_error: false,
            duration_ms: null,
            started_at: env.ts,
            finished_at: null,
          },
        },
        toolCallOrder: [...state.toolCallOrder, d.id],
      }
    }

    case "tool_result": {
      const d = env.data as ToolResultData
      const existing = state.toolCalls[d.id]
      if (!existing) return state
      return {
        ...state,
        toolCalls: {
          ...state.toolCalls,
          [d.id]: {
            ...existing,
            output: d.output,
            is_error: d.is_error,
            duration_ms: d.duration_ms,
            finished_at: env.ts,
          },
        },
      }
    }

    case "phase_start": {
      const d = env.data as PhaseStartData
      const existsAlready = state.phaseOrder.includes(d.phase)
      return {
        ...state,
        currentPhase: d.phase,
        currentPhaseStartedAt: Date.now(),
        phaseOrder: existsAlready ? state.phaseOrder : [...state.phaseOrder, d.phase],
      }
    }

    case "phase_end": {
      const d = env.data as PhaseEndData
      const stillCurrent = state.currentPhase === d.phase
      return {
        ...state,
        phaseTimings: { ...state.phaseTimings, [d.phase]: d.duration_ms },
        currentPhase: stillCurrent ? null : state.currentPhase,
        currentPhaseStartedAt: stillCurrent ? null : state.currentPhaseStartedAt,
      }
    }

    case "aborted":
      return { ...state, aborted: env.data as AbortedData, status: "aborted" }

    case "error": {
      const d = env.data as ErrorData
      return { ...state, errors: [...state.errors, d], status: "error" }
    }

    case "session_end": {
      const d = env.data as SessionEndData
      const nextStatus: RunStatus =
        state.status === "aborted"
          ? "aborted"
          : d.ok
          ? "success"
          : state.errors.length
          ? "error"
          : "aborted"
      return {
        ...state,
        status: nextStatus,
        cost_usd: d.cost_usd,
        total_turns: d.total_turns,
        duration_ms: d.duration_ms,
        currentPhase: null,
        currentPhaseStartedAt: null,
      }
    }

    default:
      return state
  }
}
