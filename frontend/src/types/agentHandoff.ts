export interface AgentHandoffSummary {
  total_messages: number;
  by_type: Record<string, number>;
  acked: number;
  unacked: number;
}

export interface AgentMessageLogEntry {
  event: string;
  timestamp?: string;
  from_agent?: string;
  to_agent?: string;
  message_type?: string;
  message_id?: string;
  priority?: number;
  acked_by?: string[];
  payload_summary?: Record<string, unknown>;
}

export function coerceAgentHandoff(value: unknown): AgentHandoffSummary | null {
  if (!value || typeof value !== 'object') return null;
  const obj = value as Record<string, unknown>;
  const byTypeRaw = obj.by_type;
  const by_type: Record<string, number> = {};
  if (byTypeRaw && typeof byTypeRaw === 'object') {
    for (const [key, raw] of Object.entries(byTypeRaw as Record<string, unknown>)) {
      const count = typeof raw === 'number' ? raw : Number(raw);
      if (Number.isFinite(count)) by_type[key] = count;
    }
  }
  return {
    total_messages: typeof obj.total_messages === 'number' ? obj.total_messages : 0,
    by_type,
    acked: typeof obj.acked === 'number' ? obj.acked : 0,
    unacked: typeof obj.unacked === 'number' ? obj.unacked : 0,
  };
}

export function formatMessageType(type: string): string {
  return type.replace(/_/g, ' ');
}

export function parseAgentMessageLog(text: string): AgentMessageLogEntry[] {
  const entries: AgentMessageLogEntry[] = [];
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;
      if (parsed.event === 'agent_message') {
        entries.push({
          event: 'agent_message',
          timestamp: typeof parsed.timestamp === 'string' ? parsed.timestamp : undefined,
          from_agent: typeof parsed.from_agent === 'string' ? parsed.from_agent : undefined,
          to_agent: typeof parsed.to_agent === 'string' ? parsed.to_agent : undefined,
          message_type: typeof parsed.message_type === 'string' ? parsed.message_type : undefined,
          message_id: typeof parsed.message_id === 'string' ? parsed.message_id : undefined,
          priority: typeof parsed.priority === 'number' ? parsed.priority : undefined,
          acked_by: Array.isArray(parsed.acked_by)
            ? parsed.acked_by.filter((v): v is string => typeof v === 'string')
            : [],
          payload_summary:
            parsed.payload_summary && typeof parsed.payload_summary === 'object'
              ? (parsed.payload_summary as Record<string, unknown>)
              : undefined,
        });
      }
    } catch {
      // Skip malformed JSONL lines (plain log text, context_usage, etc.)
    }
  }
  return entries;
}
