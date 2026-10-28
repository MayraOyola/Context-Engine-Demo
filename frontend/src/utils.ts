import type {
  ToolEvent,
  MergedToolEvent,
} from "./types";

export const modeStorageKey = "demo-domain-mode";
export const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

// Public assets must respect the Vite base path (the workshop serves this app under /app/).
export function assetUrl(path: string) {
  return `${import.meta.env.BASE_URL.replace(/\/$/, "")}${path}`;
}

export function apiUrl(path: string) {
  return apiBaseUrl ? `${apiBaseUrl}${path}` : path;
}

export function toolKindLabel(kind: ToolEvent["toolKind"]) {
  if (kind === "guardrail") return "Guardrail";
  if (kind === "memory") return "Memory";
  if (kind === "langcache") return "Semantic Cache";
  return kind === "mcp_tool" ? "Context Retriever" : "Internal";
}

export function toolDisplayName(toolName: string) {
  if (toolName === "short_term_memory_get") return "Short-term memory · GET";
  if (toolName === "long_term_memory_search") return "Long-term memory · SEARCH";
  if (toolName === "semantic_cache_search") return "Semantic cache · SEARCH";
  if (toolName === "guardrail_check") return "Semantic router · CHECK";
  if (toolName === "tool_routing") return "Tool selection · ROUTE";
  if (toolName === "agent_memory_extraction") return "Agent Memory · EXTRACTION";
  if (toolName === "get_current_user_profile") return "Current user profile";
  if (toolName === "get_current_time") return "Current time";
  if (/^search_\w+_memory$/.test(toolName)) return "Long-term memory · SEARCH";
  if (/^remember_/.test(toolName)) return "Long-term memory · CREATE";
  return toolName;
}

export function memoryEventText(event: Record<string, unknown>) {
  const content = event.content;
  if (!Array.isArray(content)) return "";
  return content
    .map((item) =>
      item && typeof item === "object" && "text" in item
        ? String((item as { text?: unknown }).text ?? "")
        : ""
    )
    .filter(Boolean)
    .join(" ");
}

export function mergeToolEvents(events: ToolEvent[]): MergedToolEvent[] {
  const merged: MergedToolEvent[] = [];
  for (const ev of events) {
    if (ev.status === "result") {
      let matched = false;
      for (let i = merged.length - 1; i >= 0; i--) {
        const candidate = merged[i];
        if (
          candidate.toolName === ev.toolName &&
          candidate.toolKind === ev.toolKind &&
          candidate.resultPayload === undefined
        ) {
          candidate.resultPayload = ev.payload;
          candidate.durationMs = ev.durationMs ?? candidate.durationMs;
          candidate.ts = candidate.ts ?? ev.ts;
          matched = true;
          break;
        }
      }
      if (!matched) {
        merged.push({
          toolName: ev.toolName,
          toolKind: ev.toolKind,
          callPayload: undefined,
          resultPayload: ev.payload,
          durationMs: ev.durationMs,
          ts: ev.ts,
        });
      }
      continue;
    }
    merged.push({
      toolName: ev.toolName,
      toolKind: ev.toolKind,
      callPayload: ev.status === "call" ? ev.payload : undefined,
      resultPayload: undefined,
      durationMs: ev.durationMs,
      ts: ev.ts,
    });
  }
  return merged;
}

function humanize(snake: string): string {
  return snake
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function generateToolDescription(toolName: string): string {
  const patterns: [RegExp, (m: RegExpMatchArray) => string][] = [
    [/^filter_(\w+?)_by_(\w+)$/, (m) => `Filter ${humanize(m[1])} by ${humanize(m[2])}`],
    [/^search_(\w+?)_by_(\w+)_similarity$/, (m) => `Semantic search on ${humanize(m[1])}.${humanize(m[2])}`],
    [/^search_(\w+?)_by_text$/, (m) => `Full-text search on ${humanize(m[1])}`],
    [/^get_(\w+?)_by_id$/, (m) => `Get ${humanize(m[1])} by ID`],
    [/^find_(\w+?)_by_(\w+)_range$/, (m) => `Range query on ${humanize(m[1])}.${humanize(m[2])}`],
  ];
  for (const [regex, formatter] of patterns) {
    const match = toolName.match(regex);
    if (match) return formatter(match);
  }
  return toolName;
}

export function extractEntity(toolName: string): string {
  const match = toolName.match(/^(?:filter|search|get|find)_(\w+?)_by/);
  return match ? humanize(match[1]) : "Other";
}


