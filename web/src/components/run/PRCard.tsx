import { motion } from "framer-motion"
import { ExternalLink, GitPullRequest } from "lucide-react"
import type { PROpenedData } from "../../types"

interface Props {
  pr: PROpenedData
}

export function PRCard({ pr }: Props) {
  return (
    <motion.a
      href={pr.url}
      target="_blank"
      rel="noopener noreferrer"
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.25 }}
      className="group flex items-start gap-3 rounded-lg border border-status-verdict/40 bg-status-verdict/10 px-4 py-3 transition-colors hover:bg-status-verdict/15 animate-verdict-glow"
    >
      <GitPullRequest size={20} className="mt-0.5 text-status-verdict" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-status-verdict">
            Pull request #{pr.number}
          </span>
        </div>
        <div className="mt-0.5 truncate font-medium">{pr.title}</div>
        <div className="mt-1 flex items-center gap-1 truncate text-xs text-muted-fg group-hover:text-fg">
          {pr.url}
          <ExternalLink size={11} className="shrink-0" />
        </div>
      </div>
    </motion.a>
  )
}
