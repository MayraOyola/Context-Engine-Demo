import { RefObject } from "react";
import type { ChatMessage } from "../types";
import { mergeToolEvents } from "../utils";
import { MarkdownMessage } from "./MarkdownMessage";

const RedisIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <path d="M7 1L12.5 3.75L7 6.5L1.5 3.75L7 1Z" fill="currentColor" opacity="0.5" />
    <path d="M12.5 6.25L7 9L1.5 6.25" stroke="currentColor" strokeWidth="1.1" fill="none" />
    <path d="M12.5 8.75L7 11.5L1.5 8.75" stroke="currentColor" strokeWidth="1.1" fill="none" />
  </svg>
);

function deriveCurrentPhase(message: ChatMessage): { label: string; redis: boolean } {
  const hasContent = message.content.length > 0;
  if (hasContent) return { label: "Generating response", redis: false };

  const hasToolCall = message.toolEvents.some(
    (e) => (e.toolKind === "mcp_tool" || e.toolKind === "internal_function") && e.status === "call"
  );
  if (hasToolCall) return { label: "Querying live context", redis: true };

  const hasMemory = message.toolEvents.some((e) => e.toolKind === "memory");
  if (hasMemory) return { label: "Recalling memories", redis: true };

  const hasCache = message.toolEvents.some((e) => e.toolKind === "langcache");
  if (hasCache) return { label: "Checking semantic cache", redis: true };

  return { label: "Initializing agent", redis: false };
}

type MessageListProps = {
  messages: ChatMessage[];
  isLoading: boolean;
  scrollRef: RefObject<HTMLDivElement | null>;
  onShowActivity: () => void;
};

export function MessageList({ messages, isLoading, scrollRef, onShowActivity }: MessageListProps) {
  return (
    <div className="message-list">
      {messages.map((message, idx) => {
        const isAssistant = message.role === "assistant";
        const isLast = idx === messages.length - 1;
        const isStreaming = isAssistant && isLast && isLoading;

        const merged = isAssistant ? mergeToolEvents(message.toolEvents) : [];
        const hasContext = merged.length > 0;

        const showPhase = isAssistant && isStreaming && !message.content;
        const phase = showPhase ? deriveCurrentPhase(message) : null;

        return (
          <article
            key={message.id}
            className={`message-row ${message.role}`}
          >
            {message.role === "user" && (
              <div className="message-user-bubble">
                <div className="message-user-text">{message.content}</div>
              </div>
            )}

            {isAssistant && (
              <div className="message-assistant-block">
                {phase && (
                  <div className="agent-phase">
                    {phase.redis && (
                      <span className="agent-phase-redis"><RedisIcon /></span>
                    )}
                    <span className="agent-phase-label">{phase.label}</span>
                  </div>
                )}
                {hasContext && (message.content || !isLoading) && (
                  <button
                    className="context-pill"
                    type="button"
                    onClick={onShowActivity}
                  >
                    <RedisIcon />
                    <span>Retrieved context from Redis</span>
                    <svg className="context-pill-chevron" width="10" height="10" viewBox="0 0 10 10" fill="none">
                      <path d="M3.5 2L6.5 5L3.5 8" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                )}
                {message.content && (
                  <div className="message-assistant-content">
                    <MarkdownMessage content={message.content} />
                    <div className="message-actions">
                      <button
                        className="message-action-btn"
                        type="button"
                        onClick={() =>
                          navigator.clipboard.writeText(message.content)
                        }
                        aria-label="Copy"
                      >
                        <svg
                          width="14"
                          height="14"
                          viewBox="0 0 14 14"
                          fill="none"
                        >
                          <rect
                            x="4.5"
                            y="4.5"
                            width="7"
                            height="8"
                            rx="1.5"
                            stroke="currentColor"
                            strokeWidth="1.2"
                          />
                          <path
                            d="M9.5 4.5V3a1.5 1.5 0 00-1.5-1.5H3A1.5 1.5 0 001.5 3v6A1.5 1.5 0 003 10.5h1.5"
                            stroke="currentColor"
                            strokeWidth="1.2"
                          />
                        </svg>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </article>
        );
      })}
      <div ref={scrollRef} />
    </div>
  );
}
