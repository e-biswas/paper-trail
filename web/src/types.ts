// Types mirroring docs/integration.md.
// These are the CANONICAL frontend-side shapes. If you add a new event type
// here, also add it to docs/integration.md in the same commit.

export type Mode = "investigate" | "check"

export type EventType =
  | "session_start"
  | "session_end"
  | "error"
  | "aborted"
  | "raw_text_delta"
  | "tool_call"
  | "tool_result"
  | "claim_summary"
  | "hypothesis"
  | "hypothesis_update"
  | "check"
  | "finding"
  | "verdict"
  | "fix_applied"
  | "metric_delta"
  | "dossier_section"
  | "pr_opened"
  | "quick_check_verdict"
  | "phase_start"
  | "phase_end"

export type PhaseName =
  | "paper_ingest"
  | "hypotheses"
  | "checks"
  | "verify"
  | "dossier"
  | "pr"

export type ModelId =
  | "claude-opus-4-7"
  | "claude-sonnet-4-6"
  | "claude-haiku-4-5-20251001"

export const ALLOWED_MODELS: ModelId[] = [
  "claude-opus-4-7",
  "claude-sonnet-4-6",
  "claude-haiku-4-5-20251001",
]

export const MODEL_LABEL: Record<ModelId, string> = {
  "claude-opus-4-7": "Opus 4.7",
  "claude-sonnet-4-6": "Sonnet 4.6",
  "claude-haiku-4-5-20251001": "Haiku 4.5",
}

export const MODEL_TAGLINE: Record<ModelId, string> = {
  "claude-opus-4-7": "Most capable · default",
  "claude-sonnet-4-6": "Balanced · faster",
  "claude-haiku-4-5-20251001": "Cheapest · fastest",
}

export const PHASE_LABEL: Record<PhaseName, string> = {
  paper_ingest: "Paper",
  hypotheses: "Hypotheses",
  checks: "Checks",
  verify: "Verify",
  dossier: "Dossier",
  pr: "PR",
}

export interface Envelope<T extends EventType = EventType, D = unknown> {
  type: T
  run_id: string
  ts: string
  seq: number
  data: D
}

// ----- per-event payloads -----

export interface SessionStartData { mode: Mode }

export interface SessionEndData {
  ok: boolean
  total_turns: number
  cost_usd: number
  duration_ms: number
  stop_reason?: string
  error?: string
}

export interface ErrorData { code: string; message: string }

export interface AbortedData { reason: string; detail?: string }

export interface ToolCallData {
  id: string
  name: string
  input: Record<string, unknown>
}

export interface ToolResultData {
  id: string
  name: string
  output: string
  is_error: boolean
  duration_ms: number
}

export interface ClaimSummaryData { claim: string }

export interface HypothesisData {
  id: string
  rank: number
  name: string
  confidence: number
  reason: string
}

export interface HypothesisUpdateData {
  id: string
  confidence: number
  reason_delta?: string
}

export interface CheckData {
  id: string
  hypothesis_id: string
  description: string
  method?: string
}

export interface FindingData {
  id: string
  check_id: string
  result: string
  supports: string[]
  refutes: string[]
}

export interface VerdictData {
  hypothesis_id: string
  confidence: number
  summary: string
}

export interface FixAppliedData {
  files_changed: string[]
  diff_summary: string
}

export interface MetricDeltaData {
  metric: string
  before: number
  after: number
  baseline?: number
  context: string
}

export type DossierSection =
  | "claim_tested"
  | "evidence_gathered"
  | "root_cause"
  | "fix_applied"
  | "remaining_uncertainty"

export interface DossierSectionData {
  section: DossierSection
  markdown: string
}

export interface PROpenedData {
  url: string
  number: number
  title: string
}

export interface EvidenceItem {
  file: string
  line: number
  snippet: string
}

export interface QuickCheckVerdictData {
  verdict: "confirmed" | "refuted" | "unclear"
  confidence: number
  evidence: EvidenceItem[]
  notes: string
}

// ----- Validator (post-run audit of a Deep Investigation) -----

export type ValidityOverall = "strong" | "acceptable" | "weak" | "unreliable"

export type ValidityMark = "pass" | "warn" | "fail"

export type ValidityCheckLabel =
  | "hypothesis_coverage"
  | "evidence_quality"
  | "fix_minimality"
  | "causal_link"
  | "alternative_explanations"
  | "uncertainty_honesty"
  | "suggested_followup"

export interface ValidityCheckItem {
  label: ValidityCheckLabel
  mark: ValidityMark
  note: string
}

export interface ValidityReportData {
  overall: ValidityOverall
  summary: string
  confidence: number
  checks: ValidityCheckItem[]
  cached?: boolean
  cost_usd?: number
  duration_ms?: number
}

// ----- Phase events -----

export interface PhaseStartData { phase: PhaseName }
export interface PhaseEndData { phase: PhaseName; duration_ms: number }

// ----- session / run summary (from REST endpoints) -----

export interface RunMeta {
  run_id: string
  mode: Mode
  session_id: string | null
  config: Record<string, unknown>
  created_at: string
  finished_at: string | null
  cost_usd: number
  total_turns: number
  duration_ms: number
  ok: boolean | null
  pr_url: string | null
  verdict_summary: string | null
  verdict_confidence: number | null
  verdict_hypothesis_id: string | null
  files_changed: string[]
  metric_deltas: MetricDeltaData[]
  paper_url: string | null
  repo_path: string | null
  repo_slug: string | null
  model?: string | null
  phase_timings?: Partial<Record<PhaseName, number>>
  first_user_text?: string | null
  validity_overall?: ValidityOverall | null
}

export interface SessionSummary {
  session_id: string
  n_runs: number
  total_cost_usd: number
  total_turns: number
  total_duration_ms: number
  pinned?: boolean
  title?: string | null
  created_at?: string
  updated_at?: string
  runs: RunMeta[]
}

export interface SessionList {
  sessions: SessionSummary[]
}
