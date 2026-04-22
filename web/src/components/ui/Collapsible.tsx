import { useState, type PropsWithChildren, type ReactNode } from "react"
import { ChevronRight } from "lucide-react"
import { cn } from "../../lib/cn"

interface Props {
  title: ReactNode
  subtitle?: ReactNode
  defaultOpen?: boolean
  badge?: ReactNode
  className?: string
}

/** Small collapsible used for Tool Stream rows, paper-summary, etc. */
export function Collapsible({
  title,
  subtitle,
  defaultOpen = false,
  badge,
  className,
  children,
}: PropsWithChildren<Props>) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={cn("rounded-md border border-border bg-card/40", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent/40"
        aria-expanded={open}
      >
        <ChevronRight
          size={14}
          className={cn(
            "text-muted-fg transition-transform",
            open && "rotate-90",
          )}
        />
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="truncate text-sm font-medium">{title}</span>
          {subtitle && (
            <span className="truncate text-xs text-muted-fg">{subtitle}</span>
          )}
        </div>
        {badge && <span className="shrink-0">{badge}</span>}
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1 animate-fade-in">{children}</div>
      )}
    </div>
  )
}
