import { Filter, X } from "lucide-react"
import { Collapsible } from "../ui/Collapsible"
import { Badge } from "../ui/Badge"
import type { ToolCallItem } from "../../state/runState"
import { cn } from "../../lib/cn"

interface Props {
  toolCalls: ToolCallItem[]
  /** Optional hypothesis-scoped filter. When set, only tool calls correlated
   *  to this hypothesis (via the last-seen `check` event before them) render. */
  filterHypothesisId?: string | null
  /** Per-tool-call hypothesis correlation map built by the reducer. */
  toolCallHypothesisId?: Record<string, string | null>
  /** Display label for the filter chip (defaults to the hypothesis id). */
  filterLabel?: string
  onClearFilter?: () => void
}

function shortInput(input: Record<string, unknown>): string {
  const file = (input as any).file_path || (input as any).path
  if (typeof file === "string") return file
  const cmd = (input as any).command
  if (typeof cmd === "string") return cmd.slice(0, 80)
  const pattern = (input as any).pattern
  if (typeof pattern === "string") return `pattern: ${pattern}`
  return JSON.stringify(input).slice(0, 80)
}

function prettyInput(input: Record<string, unknown>): string {
  return JSON.stringify(input, null, 2)
}

export function ToolStream({
  toolCalls,
  filterHypothesisId,
  toolCallHypothesisId,
  filterLabel,
  onClearFilter,
}: Props) {
  const filtering = filterHypothesisId != null
  const filtered = filtering
    ? toolCalls.filter(
        (tc) => (toolCallHypothesisId?.[tc.id] ?? null) === filterHypothesisId,
      )
    : toolCalls

  if (toolCalls.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-fg">
        No tool calls yet…
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      {filtering && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-status-checking/40 bg-status-checking/10 px-2 py-1 text-[11px] text-status-checking">
          <span className="inline-flex items-center gap-1.5">
            <Filter size={11} />
            Filtered to {filterLabel ?? filterHypothesisId}
            <span className="text-muted-fg">
              · {filtered.length}/{toolCalls.length}
            </span>
          </span>
          {onClearFilter && (
            <button
              type="button"
              onClick={onClearFilter}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-muted-fg hover:bg-accent/40 hover:text-fg"
              title="Clear hypothesis filter"
            >
              <X size={10} />
              clear
            </button>
          )}
        </div>
      )}

      {filtering && filtered.length === 0 && (
        <div className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-fg">
          No tool calls attributed to this hypothesis yet.
        </div>
      )}

      {filtered.map((tc) => {
        const done = tc.output !== null
        const isErr = tc.is_error
        return (
          <Collapsible
            key={tc.id}
            title={
              <span className="flex items-center gap-2">
                <span className="rounded bg-accent px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
                  {tc.name}
                </span>
                <span className="truncate font-normal text-muted-fg">
                  {shortInput(tc.input)}
                </span>
              </span>
            }
            badge={
              !done ? (
                <Badge tone="checking">running</Badge>
              ) : isErr ? (
                <Badge tone="refuted">error</Badge>
              ) : tc.duration_ms != null ? (
                <span className="text-[10px] text-muted-fg tabular-nums">
                  {tc.duration_ms}ms
                </span>
              ) : null
            }
          >
            <div className="space-y-2">
              <div>
                <div className="mb-1 text-[10px] uppercase tracking-wide text-muted-fg">
                  input
                </div>
                <pre className="max-h-40 overflow-auto rounded bg-black/30 p-2 text-xs leading-snug">
                  {prettyInput(tc.input)}
                </pre>
              </div>
              {done && (
                <div>
                  <div className="mb-1 text-[10px] uppercase tracking-wide text-muted-fg">
                    output
                  </div>
                  <pre
                    className={cn(
                      "max-h-64 overflow-auto rounded bg-black/30 p-2 text-xs leading-snug",
                      isErr && "text-status-refuted",
                    )}
                  >
                    {tc.output || "(empty)"}
                  </pre>
                </div>
              )}
            </div>
          </Collapsible>
        )
      })}
    </div>
  )
}
