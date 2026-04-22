import { User } from "lucide-react"
import type { UserTurn } from "../../state/chatStore"
import { Badge } from "../ui/Badge"

interface Props {
  turn: UserTurn
}

export function UserMessage({ turn }: Props) {
  const { config } = turn
  return (
    <div className="flex gap-3">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-fg">
        <User size={14} />
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center gap-2 text-xs">
          <span className="font-medium">You</span>
          <Badge tone="neutral">{turn.mode === "investigate" ? "Deep" : "Check"}</Badge>
        </div>
        <div className="prose prose-sm prose-invert max-w-none whitespace-pre-wrap break-words">
          {turn.text}
        </div>
        {(config.paper_url || config.repo_path || config.repo_slug) && (
          <div className="flex flex-wrap gap-1 text-[11px] text-muted-fg">
            {config.paper_url && (
              <span className="rounded bg-accent/50 px-1.5 py-0.5 font-mono">
                paper: {config.paper_url.length > 60 ? config.paper_url.slice(0, 57) + "…" : config.paper_url}
              </span>
            )}
            {config.repo_path && (
              <span className="rounded bg-accent/50 px-1.5 py-0.5 font-mono">
                repo: {config.repo_path}
              </span>
            )}
            {config.repo_slug && (
              <span className="rounded bg-accent/50 px-1.5 py-0.5 font-mono">
                PR target: {config.repo_slug}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
