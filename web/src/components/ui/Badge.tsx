import type { PropsWithChildren } from "react"
import { cn } from "../../lib/cn"

export type BadgeTone =
  | "neutral"
  | "pending"
  | "checking"
  | "confirmed"
  | "refuted"
  | "unclear"
  | "verdict"

const TONE_CLASS: Record<BadgeTone, string> = {
  neutral: "bg-muted text-muted-fg",
  pending: "bg-status-pending/15 text-status-pending border-status-pending/30",
  checking: "bg-status-checking/15 text-status-checking border-status-checking/30",
  confirmed: "bg-status-confirmed/15 text-status-confirmed border-status-confirmed/30",
  refuted: "bg-status-refuted/15 text-status-refuted border-status-refuted/30",
  unclear: "bg-amber-500/15 text-amber-500 border-amber-500/30",
  verdict: "bg-status-verdict/15 text-status-verdict border-status-verdict/40",
}

export function Badge({
  tone = "neutral",
  className,
  children,
}: PropsWithChildren<{ tone?: BadgeTone; className?: string }>) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-transparent px-2 py-0.5 text-xs font-medium",
        TONE_CLASS[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}
