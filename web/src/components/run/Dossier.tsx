import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Collapsible } from "../ui/Collapsible"
import type { DossierSection } from "../../types"

interface Props {
  sections: Partial<Record<DossierSection, string>>
  claim?: string | null
}

const ORDER: DossierSection[] = [
  "claim_tested",
  "evidence_gathered",
  "root_cause",
  "fix_applied",
  "remaining_uncertainty",
]

const TITLES: Record<DossierSection, string> = {
  claim_tested: "Claim tested",
  evidence_gathered: "Evidence gathered",
  root_cause: "Root cause",
  fix_applied: "Fix applied",
  remaining_uncertainty: "Remaining uncertainty",
}

export function Dossier({ sections, claim }: Props) {
  const present = ORDER.filter((k) => sections[k])
  if (present.length === 0 && !claim) return null

  return (
    <div className="rounded-lg border border-border bg-card/50 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-muted-fg">
        📄 Reproducibility Dossier
      </div>
      {claim && (
        <div className="mb-3 rounded-md border-l-2 border-status-checking bg-status-checking/5 px-3 py-2 text-sm italic">
          {claim}
        </div>
      )}
      <div className="space-y-1.5">
        {present.map((k) => (
          <Collapsible
            key={k}
            title={TITLES[k]}
            defaultOpen={k === "root_cause" || k === "fix_applied"}
          >
            <div className="prose prose-sm prose-invert max-w-none prose-p:my-1 prose-li:my-0 prose-code:text-[11px]">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {sections[k] || ""}
              </ReactMarkdown>
            </div>
          </Collapsible>
        ))}
      </div>
    </div>
  )
}
