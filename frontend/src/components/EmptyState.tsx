import type { AgentMode, DomainConfig, PromptCard } from "../types";
import { ComposerBar } from "./ComposerBar";

const EYEBROW_LABELS: Record<string, string> = {
  Context: "Context Retriever",
  Memory: "Agent Memory",
  Cached: "LangCache",
};

type EmptyStateProps = {
  domain: DomainConfig;
  backendReady: boolean;
  input: string;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  isLoading: boolean;
  mode: AgentMode;
  onModeChange: (mode: AgentMode) => void;
  starterPrompts: PromptCard[];
  onPrefill: (prompt: string) => void;
};

export function EmptyState({
  domain,
  backendReady,
  input,
  onInputChange,
  onSubmit,
  isLoading,
  mode,
  onModeChange,
  starterPrompts,
  onPrefill,
}: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div className="mode-toggle">
        <button
          className={`mode-toggle-option ${mode === "simple_rag" ? "active" : ""}`}
          onClick={() => onModeChange("simple_rag")}
          type="button"
        >
          Simple RAG
        </button>
        <button
          className={`mode-toggle-option context ${mode === "context_surfaces" ? "active" : ""}`}
          onClick={() => onModeChange("context_surfaces")}
          type="button"
        >
          Real-time Context
        </button>
      </div>

      <h1 className="empty-state-title">
        {domain?.hero_title ?? "How can we help?"}
      </h1>

      <ComposerBar
        input={input}
        onInputChange={onInputChange}
        onSubmit={onSubmit}
        isLoading={isLoading}
        placeholder={
          domain?.placeholder_text ??
          "Ask about your order, delivery status, or policies..."
        }
        variant="hero"
      />

      {!backendReady ? (
        <div className="starter-strip starter-strip--loading">
          <div className="starter-loading-label">
            <svg className="starter-loading-spinner" width="14" height="14" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.5" opacity="0.25" />
              <path d="M12.5 7A5.5 5.5 0 007 1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            Setting up demo&hellip;
          </div>
          <div className="starter-group">
            <div className="starter-chip skeleton-chip" />
            <div className="starter-chip skeleton-chip" style={{ width: 100 }} />
            <div className="starter-chip skeleton-chip" style={{ width: 140 }} />
          </div>
          <div className="starter-group">
            <div className="starter-chip skeleton-chip" style={{ width: 130 }} />
            <div className="starter-chip skeleton-chip" style={{ width: 110 }} />
          </div>
        </div>
      ) : starterPrompts.length > 0 && (() => {
        const groups = new Map<string, PromptCard[]>();
        for (const p of starterPrompts) {
          const key = p.eyebrow || "Other";
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key)!.push(p);
        }
        return (
          <div className="starter-strip">
            {[...groups.entries()].map(([eyebrow, cards]) => (
              <div key={eyebrow} className="starter-group">
                {mode === "context_surfaces" && (
                  <span className="starter-group-label">
                    {EYEBROW_LABELS[eyebrow] ?? eyebrow}
                  </span>
                )}
                <div className="starter-chips">
                  {cards.map((p) => (
                    <button
                      key={p.title}
                      className="starter-chip"
                      onClick={() => onPrefill(p.prompt)}
                      type="button"
                    >
                      {p.title}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        );
      })()}
    </div>
  );
}
