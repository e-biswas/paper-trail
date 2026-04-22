import { Download, FileText, GitPullRequest, Scroll } from "lucide-react"
import type { RunState } from "../../state/runState"

interface Props {
  runState: RunState
}

/**
 * A pill-row of artifact download buttons. Each triggers a real HTTP fetch
 * against the backend's `GET /runs/{id}/<artifact>` endpoint.
 */
export function ArtifactButtons({ runState }: Props) {
  const { run_id, dossier, fixApplied, prOpened } = runState
  if (!run_id) return null

  async function download(path: string, filename: string) {
    try {
      const res = await fetch(path)
      if (!res.ok) {
        alert(`Download failed: ${res.status} ${await res.text()}`)
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert(`Download failed: ${e}`)
    }
  }

  const hasDossier = Object.keys(dossier).length > 0
  const hasDiff = fixApplied != null

  return (
    <div className="flex flex-wrap gap-2">
      {hasDossier && (
        <button
          type="button"
          onClick={() => download(`/runs/${run_id}/dossier.md`, `dossier-${run_id}.md`)}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card/60 px-2.5 py-1 text-xs hover:bg-accent/50"
        >
          <FileText size={12} />
          dossier.md
        </button>
      )}
      {hasDiff && (
        <button
          type="button"
          onClick={() => download(`/runs/${run_id}/diff.patch`, `fix-${run_id}.patch`)}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card/60 px-2.5 py-1 text-xs hover:bg-accent/50"
        >
          <Download size={12} />
          diff.patch
        </button>
      )}
      <button
        type="button"
        onClick={() => download(`/runs/${run_id}/events.jsonl`, `events-${run_id}.jsonl`)}
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card/60 px-2.5 py-1 text-xs hover:bg-accent/50"
      >
        <Scroll size={12} />
        events.jsonl
      </button>
      {runState.mode === "investigate" && (
        <button
          type="button"
          onClick={() => download(`/runs/${run_id}/paper.md`, `paper-${run_id}.md`)}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card/60 px-2.5 py-1 text-xs hover:bg-accent/50"
        >
          <FileText size={12} />
          paper.md
        </button>
      )}
      {prOpened && (
        <a
          href={prOpened.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-md border border-status-verdict/40 bg-status-verdict/10 px-2.5 py-1 text-xs text-status-verdict hover:bg-status-verdict/20"
        >
          <GitPullRequest size={12} />
          Open PR #{prOpened.number}
        </a>
      )}
    </div>
  )
}
