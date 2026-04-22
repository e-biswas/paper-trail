import { motion } from "framer-motion"
import { Check, X, HelpCircle, FileCode } from "lucide-react"
import type { QuickCheckVerdictData } from "../../types"
import { Badge, type BadgeTone } from "../ui/Badge"
import { cn } from "../../lib/cn"

interface Props {
  verdict: QuickCheckVerdictData
}

const TONE: Record<QuickCheckVerdictData["verdict"], BadgeTone> = {
  confirmed: "confirmed",
  refuted: "refuted",
  unclear: "unclear",
}

function VerdictIcon({ v }: { v: QuickCheckVerdictData["verdict"] }) {
  if (v === "confirmed") return <Check size={16} />
  if (v === "refuted") return <X size={16} />
  return <HelpCircle size={16} />
}

export function QuickCheckVerdict({ verdict }: Props) {
  const pct = Math.round(verdict.confidence * 100)
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-2"
    >
      <div className="flex items-center gap-2">
        <Badge tone={TONE[verdict.verdict]} className="uppercase">
          <VerdictIcon v={verdict.verdict} />
          <span className="ml-0.5">{verdict.verdict}</span>
        </Badge>
        <span className="text-xs text-muted-fg tabular-nums">
          confidence {pct}%
        </span>
      </div>
      {verdict.notes && (
        <div className="rounded-md border border-border bg-card/50 px-3 py-2 text-sm leading-relaxed">
          {verdict.notes}
        </div>
      )}
      {verdict.evidence?.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-xs uppercase tracking-wide text-muted-fg">
            Evidence
          </div>
          {verdict.evidence.map((e, i) => (
            <div
              key={i}
              className={cn(
                "flex items-start gap-2 rounded-md border border-border bg-card/30 px-2.5 py-1.5 text-xs",
              )}
            >
              <FileCode size={12} className="mt-0.5 shrink-0 text-muted-fg" />
              <div className="min-w-0 flex-1">
                <div className="font-mono">
                  {e.file}
                  {typeof e.line === "number" ? `:${e.line}` : ""}
                </div>
                {e.snippet && (
                  <pre className="mt-0.5 overflow-x-auto rounded bg-black/30 px-1.5 py-1 text-[11px]">
                    {e.snippet}
                  </pre>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  )
}
