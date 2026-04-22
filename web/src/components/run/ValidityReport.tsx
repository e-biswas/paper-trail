import { motion } from "framer-motion"
import {
  BadgeCheck,
  ShieldAlert,
  ShieldQuestion,
  ShieldX,
  CheckCircle2,
  AlertTriangle,
  XCircle,
} from "lucide-react"
import type { ValidityReportData, ValidityMark, ValidityOverall } from "../../types"
import { cn } from "../../lib/cn"

interface Props {
  report: ValidityReportData
}

const OVERALL_META: Record<
  ValidityOverall,
  { icon: typeof BadgeCheck; color: string; label: string }
> = {
  strong: {
    icon: BadgeCheck,
    color: "status-confirmed",
    label: "Strong — verdict well-supported",
  },
  acceptable: {
    icon: ShieldQuestion,
    color: "status-checking",
    label: "Acceptable — verdict trustworthy, follow-ups recommended",
  },
  weak: {
    icon: ShieldAlert,
    color: "amber-500",
    label: "Weak — spot-check before relying on the verdict",
  },
  unreliable: {
    icon: ShieldX,
    color: "status-refuted",
    label: "Unreliable — human re-read advised",
  },
}

const MARK_ICON: Record<ValidityMark, typeof CheckCircle2> = {
  pass: CheckCircle2,
  warn: AlertTriangle,
  fail: XCircle,
}

const MARK_COLOR: Record<ValidityMark, string> = {
  pass: "text-status-confirmed",
  warn: "text-amber-500",
  fail: "text-status-refuted",
}

const LABEL_PRETTY: Record<string, string> = {
  hypothesis_coverage: "Hypothesis coverage",
  evidence_quality: "Evidence quality",
  fix_minimality: "Fix minimality",
  causal_link: "Causal link",
  alternative_explanations: "Alternative explanations",
  uncertainty_honesty: "Honesty of uncertainty",
  suggested_followup: "Suggested follow-up",
}


export function ValidityReport({ report }: Props) {
  const { overall, summary, checks, confidence, cost_usd, cached } = report
  const meta = OVERALL_META[overall] ?? OVERALL_META.acceptable
  const OverallIcon = meta.icon

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={cn(
        "rounded-lg border border-border bg-card/60",
        "shadow-[0_0_0_1px_rgba(255,255,255,0.02)_inset]",
      )}
    >
      {/* Header */}
      <div className="flex items-start gap-3 border-b border-border/60 px-4 py-3">
        <OverallIcon size={18} className={cn("mt-0.5 shrink-0", `text-${meta.color}`)} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-muted-fg">
              Independent validity review
            </span>
            <span
              className={cn(
                "rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                overall === "strong"
                  ? "border-status-confirmed/40 bg-status-confirmed/10 text-status-confirmed"
                  : overall === "acceptable"
                  ? "border-status-checking/40 bg-status-checking/10 text-status-checking"
                  : overall === "weak"
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-500"
                  : "border-status-refuted/40 bg-status-refuted/10 text-status-refuted",
              )}
            >
              {overall}
            </span>
            {typeof confidence === "number" && (
              <span className="text-[10px] tabular-nums text-muted-fg">
                reviewer conf {Math.round(confidence * 100)}%
              </span>
            )}
            {cached && (
              <span className="rounded bg-accent px-1.5 py-0.5 text-[10px] text-muted-fg">
                cached
              </span>
            )}
            {typeof cost_usd === "number" && cost_usd > 0 && (
              <span className="text-[10px] tabular-nums text-muted-fg">
                ${cost_usd.toFixed(4)}
              </span>
            )}
          </div>
          <div className="mt-1 text-sm leading-snug">{summary || meta.label}</div>
        </div>
      </div>

      {/* Checks */}
      <div className="divide-y divide-border/60">
        {checks.map((c, i) => {
          const Icon = MARK_ICON[c.mark] ?? MARK_ICON.warn
          return (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -4 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.18, delay: i * 0.03 }}
              className="flex items-start gap-3 px-4 py-2.5"
            >
              <Icon size={14} className={cn("mt-0.5 shrink-0", MARK_COLOR[c.mark])} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium">
                    {LABEL_PRETTY[c.label] ?? c.label}
                  </span>
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                      c.mark === "pass"
                        ? "bg-status-confirmed/10 text-status-confirmed"
                        : c.mark === "warn"
                        ? "bg-amber-500/10 text-amber-500"
                        : "bg-status-refuted/10 text-status-refuted",
                    )}
                  >
                    {c.mark}
                  </span>
                </div>
                <div className="mt-0.5 text-xs leading-relaxed text-muted-fg">
                  {c.note}
                </div>
              </div>
            </motion.div>
          )
        })}
      </div>
    </motion.div>
  )
}
