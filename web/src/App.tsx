import { useEffect, useRef } from "react"
import { useChatStore } from "./state/chatStore"
import { Sidebar } from "./components/chat/Sidebar"
import { InputRow } from "./components/chat/InputRow"
import { UserMessage } from "./components/chat/UserMessage"
import { AssistantMessage } from "./components/chat/AssistantMessage"
import { Telescope, Sparkles } from "lucide-react"

const DEFAULT_REPO_PATH = "/tmp/muchlinski-demo"
const DEFAULT_REPO_SLUG = "e-biswas/reproforensics-muchlinski-demo"
const DEFAULT_PAPER_URL = "test_data/papers/muchlinski.md"

function EmptyState() {
  return (
    <div className="mx-auto max-w-2xl py-20 text-center">
      <div className="mb-6 inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-status-checking/15 text-status-checking">
        <Telescope size={28} />
      </div>
      <h1 className="mb-2 text-2xl font-semibold tracking-tight">
        Paper Trail
      </h1>
      <p className="mx-auto max-w-md text-sm text-muted-fg">
        A verification intern for research engineers. Ask a{" "}
        <span className="font-medium text-status-checking">Quick Check</span>{" "}
        about a repo, or kick off a{" "}
        <span className="font-medium text-status-verdict">Deep Investigation</span>{" "}
        that ends in a real GitHub PR.
      </p>

      <div className="mx-auto mt-8 grid max-w-xl grid-cols-1 gap-2 text-left sm:grid-cols-2">
        {[
          {
            mode: "Quick Check",
            example: "Is imputation fit only on training data?",
          },
          {
            mode: "Quick Check",
            example: "Are there duplicate rows between train and test?",
          },
          {
            mode: "Deep",
            example: "Investigate why this paper's claim doesn't reproduce.",
          },
          {
            mode: "Deep",
            example: "Audit this repo and open a fix PR if there's leakage.",
          },
        ].map((ex, i) => (
          <div
            key={i}
            className="rounded-md border border-border bg-card/40 px-3 py-2 text-sm"
          >
            <div className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-fg">
              <Sparkles size={10} />
              {ex.mode}
            </div>
            <div className="text-fg/90">{ex.example}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function App() {
  const store = useChatStore()
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to latest message when the last assistant turn updates.
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    })
  }, [store.turns])

  return (
    <div className="flex h-screen w-screen bg-bg text-fg">
      <Sidebar
        sessionId={store.sessionId}
        turns={store.turns}
        isRunning={store.isRunning}
        onNewSession={store.newSession}
        onLoadSession={store.loadSession}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-4 py-6">
            {store.turns.length === 0 ? (
              <EmptyState />
            ) : (
              <div className="space-y-8">
                {store.turns.map((t) =>
                  t.kind === "user" ? (
                    <UserMessage key={t.id} turn={t} />
                  ) : (
                    <AssistantMessage
                      key={t.id}
                      turn={t}
                      onValidate={store.validateRun}
                      onStop={store.isRunning ? store.stopRun : undefined}
                      onSelectHypothesis={store.setSelectedHypothesis}
                    />
                  ),
                )}
              </div>
            )}
          </div>
        </div>

        {store.error && (
          <div className="mx-auto mb-2 max-w-3xl rounded-md border border-status-refuted/50 bg-status-refuted/10 px-3 py-2 text-sm text-status-refuted">
            {store.error}
          </div>
        )}

        <div className="border-t border-border bg-bg/90 px-4 py-3 backdrop-blur">
          <InputRow
            onSubmit={store.startRun}
            disabled={store.isRunning}
            defaultRepoPath={DEFAULT_REPO_PATH}
            defaultRepoSlug={DEFAULT_REPO_SLUG}
            defaultPaperUrl={DEFAULT_PAPER_URL}
          />
        </div>
      </main>
    </div>
  )
}
