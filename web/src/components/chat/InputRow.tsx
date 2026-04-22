import {
  useState,
  useRef,
  useEffect,
  type KeyboardEvent,
  type ChangeEvent,
  useCallback,
} from "react"
import {
  ChevronDown,
  Send,
  Telescope,
  CircleHelp,
  Loader2,
  FileCheck2,
  Plus,
  SlidersHorizontal,
  Check,
  CircleX,
  GitBranch,
  FolderOpen,
} from "lucide-react"
import type { Mode, ModelId } from "../../types"
import { ALLOWED_MODELS, MODEL_LABEL, MODEL_TAGLINE } from "../../types"
import type { StartRunInput } from "../../state/chatStore"
import { cn } from "../../lib/cn"

interface Props {
  onSubmit: (input: StartRunInput) => void
  disabled: boolean
  defaultRepoPath: string
  defaultRepoSlug?: string | null
  defaultPaperUrl?: string
}

interface RepoResolution {
  local_path: string
  slug: string | null
  default_branch: string | null
  source: "clone" | "cache" | "local"
  already_cloned: boolean
  warning: string | null
}

const MODE_META: Record<
  Mode,
  { label: string; icon: typeof Telescope; tagline: string }
> = {
  check: {
    label: "Quick Check",
    icon: CircleHelp,
    tagline: "≤8 turns · ≤$1 · no PR",
  },
  investigate: {
    label: "Deep Investigation",
    icon: Telescope,
    tagline: "≤30 turns · ≤$5 · opens real PR when slug set",
  },
}

function RepoStatusPill({
  resolution,
  status,
  errorMessage,
}: {
  resolution: RepoResolution | null
  status: "idle" | "attaching" | "error"
  errorMessage: string | null
}) {
  if (status === "attaching") {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-muted-fg">
        <Loader2 size={10} className="animate-spin" />
        cloning / resolving…
      </span>
    )
  }
  if (status === "error" && errorMessage) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-status-refuted">
        <CircleX size={10} />
        {errorMessage}
      </span>
    )
  }
  if (!resolution) {
    return (
      <span className="text-[10px] text-muted-fg/80">
        Not attached yet. Press Enter or click <kbd className="rounded border border-border/60 px-1">Attach</kbd>.
      </span>
    )
  }
  const Icon =
    resolution.source === "local" ? FolderOpen : GitBranch
  const label =
    resolution.slug ||
    (resolution.source === "local"
      ? resolution.local_path
      : resolution.local_path)
  const source = {
    clone: "cloned",
    cache: "cached",
    local: "local",
  }[resolution.source]
  return (
    <span
      className={cn(
        "inline-flex flex-wrap items-center gap-1 text-[10px]",
        "text-status-confirmed",
      )}
    >
      <Check size={10} />
      <Icon size={10} />
      <span className="font-mono">{label}</span>
      <span className="text-muted-fg">
        · {source}
        {resolution.default_branch ? ` · branch: ${resolution.default_branch}` : ""}
      </span>
      {resolution.warning && (
        <span className="text-status-refuted">· ⚠ {resolution.warning}</span>
      )}
    </span>
  )
}

/** Does the user's typed input match what we already resolved? */
function _matchesResolution(input: string, r: RepoResolution): boolean {
  const i = input.trim()
  return (
    i === r.local_path ||
    i === r.slug ||
    (r.slug != null && i.toLowerCase() === `https://github.com/${r.slug}`.toLowerCase()) ||
    (r.slug != null && i.toLowerCase() === `https://github.com/${r.slug}.git`.toLowerCase())
  )
}

/** Claude-Code-style composer: textarea grows upward, controls inside the box. */
export function InputRow({
  onSubmit,
  disabled,
  defaultRepoPath,
  defaultRepoSlug,
  defaultPaperUrl,
}: Props) {
  const [mode, setMode] = useState<Mode>("check")
  const [model, setModel] = useState<ModelId>(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem("repro.model") : null
    if (saved && ALLOWED_MODELS.includes(saved as ModelId)) return saved as ModelId
    return "claude-opus-4-7"
  })
  const [text, setText] = useState("")
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [modeMenuOpen, setModeMenuOpen] = useState(false)
  const [modelMenuOpen, setModelMenuOpen] = useState(false)

  // Single unified repo field. The value is anything the user types — a
  // GitHub URL, a bare `owner/repo` slug, or a local path. On attach, the
  // backend resolves it into `{ local_path, slug, default_branch }` which
  // we cache in `repoResolution`.
  const [repoInput, setRepoInput] = useState(
    defaultRepoSlug || defaultRepoPath || "",
  )
  const [repoResolution, setRepoResolution] = useState<RepoResolution | null>(
    null,
  )
  const [repoAttachStatus, setRepoAttachStatus] = useState<
    "idle" | "attaching" | "error"
  >("idle")
  const [repoAttachError, setRepoAttachError] = useState<string | null>(null)

  const [paperUrl, setPaperUrl] = useState(defaultPaperUrl ?? "")
  const [uploadedName, setUploadedName] = useState<string | null>(null)
  const [uploadState, setUploadState] = useState<"idle" | "uploading" | "error">(
    "idle",
  )
  const [uploadError, setUploadError] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const modeMenuRef = useRef<HTMLDivElement>(null)
  const modelMenuRef = useRef<HTMLDivElement>(null)

  // Persist model choice so it survives reloads.
  useEffect(() => {
    try {
      localStorage.setItem("repro.model", model)
    } catch {
      // localStorage disabled; ignore
    }
  }, [model])

  // Close popovers on outside click.
  useEffect(() => {
    function onDoc(ev: MouseEvent) {
      const target = ev.target as Node | null
      if (!target) return
      if (modeMenuOpen && modeMenuRef.current && !modeMenuRef.current.contains(target))
        setModeMenuOpen(false)
      if (modelMenuOpen && modelMenuRef.current && !modelMenuRef.current.contains(target))
        setModelMenuOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [modeMenuOpen, modelMenuOpen])

  // Resolve the current `repoInput` via the backend, cache the result, and
  // return it. Used both by the explicit "Attach" button and implicitly on
  // submit if the user hasn't attached yet.
  const attachRepo = useCallback(
    async (input: string): Promise<RepoResolution | null> => {
      const trimmed = input.trim()
      if (!trimmed) return null
      setRepoAttachStatus("attaching")
      setRepoAttachError(null)
      try {
        const res = await fetch(
          `/repos/attach?input=${encodeURIComponent(trimmed)}`,
          { method: "POST" },
        )
        // Read the body as text first so 404/HTML responses produce a
        // useful error instead of blowing up inside res.json().
        const rawText = await res.text()
        let body: unknown = null
        if (rawText) {
          try {
            body = JSON.parse(rawText)
          } catch {
            // non-JSON body; fall through to status-based message
          }
        }
        if (!res.ok) {
          const detail =
            (body as { detail?: string } | null)?.detail ||
            (rawText ? rawText.slice(0, 160) : `HTTP ${res.status}`)
          if (res.status === 404) {
            throw new Error(
              "backend /repos/attach not reachable — is the server on :8080 running? " +
                "If you just updated vite.config.ts, restart `npm run dev`.",
            )
          }
          throw new Error(detail)
        }
        const resolved = body as RepoResolution
        setRepoResolution(resolved)
        setRepoAttachStatus("idle")
        return resolved
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err)
        setRepoAttachStatus("error")
        setRepoAttachError(msg)
        setRepoResolution(null)
        return null
      }
    },
    [],
  )

  async function handlePdfUpload(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setUploadState("uploading")
    setUploadError(null)
    try {
      const form = new FormData()
      form.append("file", f)
      const res = await fetch("/papers/upload", { method: "POST", body: form })
      if (!res.ok) {
        const txt = await res.text()
        throw new Error(`upload failed: ${res.status} ${txt.slice(0, 200)}`)
      }
      const body = (await res.json()) as {
        path: string
        filename: string
        size_bytes: number
      }
      setPaperUrl(body.path)
      setUploadedName(body.filename)
      setUploadState("idle")
    } catch (err: unknown) {
      setUploadState("error")
      setUploadError(err instanceof Error ? err.message : String(err))
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ""
    }
  }

  // Auto-resize textarea: grows upward as content adds lines.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = Math.min(320, el.scrollHeight) + "px"
  }, [text])

  const handleSubmit = useCallback(async () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return

    // Resolve the repo if the user typed a new value since the last attach.
    let resolved = repoResolution
    if (!resolved || resolved.local_path === "" ||
      (repoInput.trim() && !_matchesResolution(repoInput.trim(), resolved))) {
      resolved = await attachRepo(repoInput)
      if (!resolved && repoInput.trim()) {
        // Attach failed; keep the form populated so the user can fix it.
        return
      }
    }

    const repo_path = resolved?.local_path || repoInput.trim() || undefined
    const repo_slug =
      mode === "investigate" && resolved?.slug ? resolved.slug : null

    onSubmit({
      mode,
      text: trimmed,
      paper_url:
        mode === "investigate" ? paperUrl.trim() || undefined : undefined,
      repo_path,
      repo_slug,
      model,
    })
    setText("")
  }, [
    text,
    disabled,
    mode,
    paperUrl,
    repoInput,
    repoResolution,
    attachRepo,
    onSubmit,
    model,
  ])

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      void handleSubmit()
    }
  }

  const ModeIcon = MODE_META[mode].icon

  return (
    <div className="mx-auto w-full max-w-3xl">
      {/* Config drawer (collapsed by default) — appears ABOVE the box */}
      {showAdvanced && (
        <div className="mb-2 flex flex-col gap-2 rounded-xl border border-border bg-card/60 px-3 py-2.5 text-xs">
          {/* Unified repo field — GitHub URL, slug, or local path.
              Backend clones & resolves slug + default_branch. */}
          <label className="flex flex-col gap-1">
            <span className="flex items-center justify-between text-muted-fg">
              <span className="inline-flex items-center gap-1.5">
                <GitBranch size={11} />
                Repo · paste a GitHub URL, <code className="font-mono">owner/repo</code>, or a local path
              </span>
              {mode === "investigate" && (
                <span className="text-[10px] text-muted-fg">
                  slug auto-fills for PR target
                </span>
              )}
            </span>
            <div className="flex gap-1.5">
              <input
                value={repoInput}
                onChange={(e) => {
                  setRepoInput(e.target.value)
                  // Invalidate resolution when user edits; it'll re-attach on submit.
                  if (repoResolution && !_matchesResolution(e.target.value, repoResolution)) {
                    setRepoResolution(null)
                    setRepoAttachStatus("idle")
                    setRepoAttachError(null)
                  }
                }}
                onBlur={() => {
                  // Auto-attach on blur if input is non-empty and unresolved.
                  if (
                    repoInput.trim() &&
                    !repoResolution &&
                    repoAttachStatus !== "attaching"
                  ) {
                    void attachRepo(repoInput)
                  }
                }}
                placeholder="e-biswas/reproforensics-muchlinski-demo  ·  https://github.com/…  ·  /tmp/muchlinski-demo"
                className="flex-1 rounded-md border border-border bg-input px-2 py-1.5 font-mono text-xs focus:border-ring focus:outline-none"
              />
              <button
                type="button"
                onClick={() => void attachRepo(repoInput)}
                disabled={!repoInput.trim() || repoAttachStatus === "attaching"}
                className={cn(
                  "inline-flex items-center gap-1 rounded-md border border-border px-2 py-1",
                  "bg-input/60 text-[11px] font-medium hover:bg-accent/50",
                  "disabled:cursor-not-allowed disabled:opacity-60",
                )}
                title="Clone (or reuse) and resolve the slug + default branch"
              >
                {repoAttachStatus === "attaching" ? (
                  <>
                    <Loader2 size={11} className="animate-spin" />
                    attaching…
                  </>
                ) : (
                  "Attach"
                )}
              </button>
            </div>
            <RepoStatusPill
              resolution={repoResolution}
              status={repoAttachStatus}
              errorMessage={repoAttachError}
            />
          </label>

          {/* Paper field — only shown in investigate mode (Quick Check doesn't use one) */}
          {mode === "investigate" && (
            <label className="flex flex-col gap-1">
              <span className="text-muted-fg">
                Paper URL or local path
                <span className="ml-1 text-[10px]">
                  (or use the <kbd className="rounded border border-border px-1">+</kbd> button in the composer to upload a PDF)
                </span>
              </span>
              <input
                value={paperUrl}
                onChange={(e) => {
                  setPaperUrl(e.target.value)
                  if (uploadedName) setUploadedName(null)
                }}
                placeholder="https://arxiv.org/abs/…  ·  /tmp/paper.pdf  ·  test_data/papers/muchlinski.md"
                className="rounded-md border border-border bg-input px-2 py-1.5 font-mono text-xs focus:border-ring focus:outline-none"
              />
              {uploadError && (
                <span className="text-[10px] text-status-refuted">⚠ {uploadError}</span>
              )}
            </label>
          )}
        </div>
      )}

      {/* Composer — unified rounded box with textarea on top, toolbar on bottom */}
      <div
        className={cn(
          "flex flex-col rounded-2xl border border-border bg-card/70 shadow-lg shadow-black/30 transition",
          "focus-within:border-ring focus-within:shadow-black/40",
          disabled && "opacity-80",
        )}
      >
        {/* Textarea — grows upward with content */}
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKey}
          rows={1}
          placeholder={
            mode === "check"
              ? "Ask a verification question about the repo…"
              : "What should the agent investigate? (paper claim, hypothesis to start from)"
          }
          className={cn(
            "w-full resize-none bg-transparent px-4 py-3 text-sm leading-relaxed",
            "placeholder-muted-fg focus:outline-none",
          )}
          style={{ minHeight: 48, maxHeight: 320 }}
          disabled={disabled}
          aria-label="Prompt"
        />

        {/* Toolbar — mirrors Claude Code's bottom-row layout */}
        <div className="flex items-center gap-1 border-t border-border/60 px-2 py-1.5">
          {/* Attach PDF shortcut (only visible in investigate mode) */}
          {mode === "investigate" && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept="application/pdf,.pdf"
                className="hidden"
                onChange={handlePdfUpload}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploadState === "uploading" || disabled}
                className={cn(
                  "inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-fg",
                  "hover:bg-accent/50 hover:text-fg disabled:cursor-not-allowed disabled:opacity-50",
                )}
                title={uploadedName ? `Attached: ${uploadedName}` : "Attach a PDF"}
              >
                {uploadState === "uploading" ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : uploadedName ? (
                  <FileCheck2 size={14} className="text-status-confirmed" />
                ) : (
                  <Plus size={14} />
                )}
              </button>
            </>
          )}

          {/* Config / advanced toggle */}
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className={cn(
              "inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-fg",
              "hover:bg-accent/50 hover:text-fg",
              showAdvanced && "bg-accent/50 text-fg",
            )}
            title={showAdvanced ? "Hide config" : "Show paper/repo config"}
          >
            <SlidersHorizontal size={14} />
          </button>

          {/* uploaded-name pill (if any) */}
          {uploadedName && (
            <span
              className="ml-1 inline-flex max-w-[180px] items-center gap-1 truncate rounded-md border border-status-confirmed/30 bg-status-confirmed/10 px-1.5 py-0.5 text-[10px] text-status-confirmed"
              title={uploadedName}
            >
              <FileCheck2 size={10} className="shrink-0" />
              <span className="truncate">{uploadedName}</span>
            </span>
          )}

          <div className="flex-1" />

          {/* Mode selector */}
          <div ref={modeMenuRef} className="relative">
            <button
              type="button"
              onClick={() => {
                setModeMenuOpen((v) => !v)
                setModelMenuOpen(false)
              }}
              disabled={disabled}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs",
                "border border-border bg-input/60 hover:bg-accent/40",
                "disabled:cursor-not-allowed disabled:opacity-60",
              )}
              title="Switch between Quick Check and Deep Investigation"
            >
              <ModeIcon size={12} className="text-status-checking" />
              <span className="font-medium">{MODE_META[mode].label}</span>
              <ChevronDown size={11} className="text-muted-fg" />
            </button>
            {modeMenuOpen && (
              <div
                className={cn(
                  "absolute bottom-9 right-0 z-20 w-64 overflow-hidden rounded-lg border border-border",
                  "bg-card shadow-lg shadow-black/40",
                )}
              >
                {(["check", "investigate"] as Mode[]).map((m) => {
                  const Meta = MODE_META[m]
                  const MetaIcon = Meta.icon
                  return (
                    <button
                      key={m}
                      type="button"
                      onClick={() => {
                        setMode(m)
                        setModeMenuOpen(false)
                      }}
                      className={cn(
                        "flex w-full items-start gap-2 px-3 py-2 text-left text-xs",
                        m === mode ? "bg-accent/40" : "hover:bg-accent/20",
                      )}
                    >
                      <MetaIcon size={13} className="mt-0.5 text-status-checking" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">{Meta.label}</span>
                          {m === mode && <Check size={12} className="text-status-confirmed" />}
                        </div>
                        <div className="text-[10px] text-muted-fg">{Meta.tagline}</div>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* Model selector */}
          <div ref={modelMenuRef} className="relative">
            <button
              type="button"
              onClick={() => {
                setModelMenuOpen((v) => !v)
                setModeMenuOpen(false)
              }}
              disabled={disabled}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs",
                "border border-border bg-input/60 hover:bg-accent/40",
                "disabled:cursor-not-allowed disabled:opacity-60",
              )}
              title="Choose the Claude model this run uses"
            >
              <span className="font-medium">{MODEL_LABEL[model]}</span>
              <ChevronDown size={11} className="text-muted-fg" />
            </button>
            {modelMenuOpen && (
              <div
                className={cn(
                  "absolute bottom-9 right-0 z-20 w-56 overflow-hidden rounded-lg border border-border",
                  "bg-card shadow-lg shadow-black/40",
                )}
              >
                {ALLOWED_MODELS.map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => {
                      setModel(m)
                      setModelMenuOpen(false)
                    }}
                    className={cn(
                      "flex w-full items-start gap-2 px-3 py-2 text-left text-xs",
                      m === model ? "bg-accent/40" : "hover:bg-accent/20",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{MODEL_LABEL[m]}</span>
                        {m === model && <Check size={12} className="text-status-confirmed" />}
                      </div>
                      <div className="text-[10px] text-muted-fg">{MODEL_TAGLINE[m]}</div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Send */}
          <button
            type="button"
            onClick={handleSubmit}
            disabled={disabled || !text.trim()}
            className={cn(
              "inline-flex h-7 w-7 items-center justify-center rounded-md bg-status-checking text-white shadow-sm",
              "hover:bg-status-checking/90 disabled:cursor-not-allowed disabled:opacity-40",
            )}
            title="Send (Enter)"
          >
            <Send size={13} />
          </button>
        </div>
      </div>

      {/* Single-line footnote below the box — same pattern as Claude Code */}
      <div className="mt-1.5 flex items-center justify-center gap-1.5 text-[10px] text-muted-fg">
        <ModeIcon size={10} />
        <span>{MODE_META[mode].tagline}</span>
        <span>·</span>
        <span>{MODEL_LABEL[model]}</span>
        <span>·</span>
        <span>⏎ send · ⇧⏎ newline</span>
      </div>
    </div>
  )
}
