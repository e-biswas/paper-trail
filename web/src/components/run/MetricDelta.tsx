import { motion } from "framer-motion"
import type { MetricDeltaData } from "../../types"
import { cn } from "../../lib/cn"
import { TrendingDown, TrendingUp, Minus } from "lucide-react"

interface Props {
  deltas: MetricDeltaData[]
}

function fmt(n: number): string {
  if (Math.abs(n) >= 100) return n.toFixed(1)
  return n.toFixed(4)
}

export function MetricDelta({ deltas }: Props) {
  if (deltas.length === 0) return null
  return (
    <div className="space-y-1.5">
      {deltas.map((d, i) => {
        const change = d.after - d.before
        const pct = d.before !== 0 ? (change / d.before) * 100 : 0
        const icon =
          change < -0.0001 ? (
            <TrendingDown size={14} className="text-status-refuted" />
          ) : change > 0.0001 ? (
            <TrendingUp size={14} className="text-status-confirmed" />
          ) : (
            <Minus size={14} className="text-muted-fg" />
          )
        const sign = change > 0 ? "+" : ""
        return (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-md border border-border bg-card/60 px-3 py-2"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="truncate text-sm">
                <span className="font-medium">{d.metric}</span>
                {d.context && (
                  <span className="ml-2 text-xs text-muted-fg">· {d.context}</span>
                )}
              </div>
              {icon}
            </div>
            <div className="mt-1 flex items-baseline gap-2 font-mono">
              <span className="text-lg tabular-nums">{fmt(d.before)}</span>
              <span className="text-muted-fg">→</span>
              <span
                className={cn(
                  "text-lg tabular-nums",
                  change < 0 ? "text-status-refuted" : change > 0 ? "text-status-confirmed" : "",
                )}
              >
                {fmt(d.after)}
              </span>
              <span
                className={cn(
                  "ml-2 text-xs tabular-nums",
                  change < 0 ? "text-status-refuted" : change > 0 ? "text-status-confirmed" : "text-muted-fg",
                )}
              >
                {sign}
                {fmt(change)} ({sign}
                {pct.toFixed(1)}%)
              </span>
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}
