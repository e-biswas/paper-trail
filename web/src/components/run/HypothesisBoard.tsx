import { motion } from "framer-motion"
import { Trophy, Check, X, Loader2 } from "lucide-react"
import type { HypothesisItem } from "../../state/runState"
import { cn } from "../../lib/cn"

interface Props {
  hypotheses: HypothesisItem[]
}

const STATUS_BORDER: Record<HypothesisItem["status"], string> = {
  pending: "border-l-status-pending",
  checking: "border-l-status-checking",
  confirmed: "border-l-status-confirmed",
  refuted: "border-l-status-refuted",
  verdict: "border-l-status-verdict",
}

const STATUS_BAR: Record<HypothesisItem["status"], string> = {
  pending: "bg-status-pending",
  checking: "bg-status-checking",
  confirmed: "bg-status-confirmed",
  refuted: "bg-status-refuted",
  verdict: "bg-status-verdict",
}

function StatusIcon({ status }: { status: HypothesisItem["status"] }) {
  if (status === "verdict") return <Trophy size={14} className="text-status-verdict" />
  if (status === "confirmed") return <Check size={14} className="text-status-confirmed" />
  if (status === "refuted") return <X size={14} className="text-status-refuted" />
  if (status === "checking") return <Loader2 size={14} className="animate-spin text-status-checking" />
  return null
}

export function HypothesisBoard({ hypotheses }: Props) {
  if (hypotheses.length === 0) return null

  return (
    <div className="space-y-2">
      {hypotheses.map((h) => {
        const pct = Math.round(h.confidence * 100)
        return (
          <motion.div
            key={h.id}
            layout
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className={cn(
              "rounded-md border bg-card/60 border-border border-l-4 px-3 py-2",
              STATUS_BORDER[h.status],
              h.status === "verdict" && "ring-1 ring-status-verdict/40 animate-verdict-glow",
            )}
          >
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-fg tabular-nums">#{h.rank}</span>
              <span className="flex-1 text-sm font-medium truncate">{h.name}</span>
              <StatusIcon status={h.status} />
              <span className="text-xs tabular-nums text-muted-fg">{pct}%</span>
            </div>

            <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-border/60">
              <motion.div
                className={cn("h-full", STATUS_BAR[h.status])}
                initial={{ width: 0 }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.4, ease: "easeOut" }}
              />
            </div>

            <div className="mt-1.5 text-xs text-muted-fg line-clamp-2">{h.reason}</div>
            {h.reasonDelta && (
              <div className="mt-1 text-xs italic text-muted-fg">↑ {h.reasonDelta}</div>
            )}
          </motion.div>
        )
      })}
    </div>
  )
}
