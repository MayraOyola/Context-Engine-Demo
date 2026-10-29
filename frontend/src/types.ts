export type ChatRole = "user" | "assistant";

export type ToolEvent = {
  toolName: string;
  toolKind: "internal_function" | "mcp_tool" | "memory" | "langcache" | "guardrail";
  status: "call" | "result";
  payload: Record<string, unknown>;
  durationMs?: number;
  ts?: number;
};

export type MergedToolEvent = {
  toolName: string;
  toolKind: ToolEvent["toolKind"];
  callPayload?: Record<string, unknown>;
  resultPayload?: Record<string, unknown>;
  durationMs?: number;
  ts?: number;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  toolEvents: ToolEvent[];
};

export type HealthState = {
  ok: boolean;
  domain: string;
  mcp_enabled: boolean;
  memory_enabled?: boolean;
  langcache_enabled?: boolean;
  internal_tools: string[];
} | null;

export type MemoryDashboardState = {
  enabled: boolean;
  thread_id?: string | null;
  owner_id?: string;
  short_term: Array<{ role: string; text: string }>;
  long_term: Array<{ id: string; text: string; [key: string]: unknown }>;
  errors?: string[];
} | null;

export type PromptCard = { eyebrow: string; title: string; prompt: string };

export type DomainConfig = {
  id: string;
  app_name: string;
  subtitle: string;
  hero_title: string;
  placeholder_text: string;
  demo_steps: string[];
  starter_prompts: PromptCard[];
  theme: Record<string, string>;
  logo_src: string;
  seed_langcache?: { prompt: string; response: string }[];
  members?: { id: string; name: string; plan: string; story: string }[];
  default_member_id?: string;
} | null;

export type ToolDefinition = {
  name: string;
  description: string;
  kind: "internal" | "mcp_tool";
  input_schema?: Record<string, unknown>;
};

export type ToolsResponse = {
  tools: ToolDefinition[];
  count: number;
};

export type RedisContextView = "activity" | "redis-context";
