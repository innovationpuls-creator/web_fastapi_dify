import { describe, expect, it } from "vitest";
import { resolveLastTurnActions } from "./turnActions";
import type { DisplayMessage } from "./model";

const baseTimestamp = "2026-03-14T12:00:00.000Z";

const createMessage = (overrides: Partial<DisplayMessage>): DisplayMessage => ({
  clientKey: overrides.clientKey ?? overrides.id ?? "message-1",
  id: overrides.id ?? "message-1",
  conversation_id: overrides.conversation_id ?? "conversation-1",
  role: overrides.role ?? "assistant",
  status: overrides.status ?? "completed",
  parts: overrides.parts ?? [{ type: "text", text: "Hello" }],
  created_at: overrides.created_at ?? baseTimestamp,
  updated_at: overrides.updated_at ?? baseTimestamp,
  thinking_completed_at: overrides.thinking_completed_at ?? null,
  model: overrides.model ?? null,
  finish_reason: overrides.finish_reason ?? null,
  error: overrides.error ?? null,
  metrics: overrides.metrics ?? null,
  isSkeleton: overrides.isSkeleton,
});

describe("resolveLastTurnActions", () => {
  it("marks the final pure-text user message as editable and the paired assistant as regenerable", () => {
    const user = createMessage({
      id: "user-last",
      clientKey: "user-last",
      role: "user",
      parts: [{ type: "text", text: "Refine this" }],
    });
    const assistant = createMessage({
      id: "assistant-last",
      clientKey: "assistant-last",
      role: "assistant",
      parts: [{ type: "text", text: "Here is a revision" }],
      metrics: {
        input_tokens: 120,
        output_tokens: 222,
        total_tokens: 342,
        latency_ms: 1200,
      },
    });

    expect(resolveLastTurnActions([user, assistant], false)).toEqual({
      editableUserMessageId: "user-last",
      regenerableAssistantMessageId: "assistant-last",
      assistantMetrics: assistant.metrics,
    });
  });

  it("hides the edit action when the latest user message contains images", () => {
    const user = createMessage({
      id: "user-image",
      clientKey: "user-image",
      role: "user",
      parts: [
        { type: "text", text: "Please analyze this" },
        {
          type: "image",
          asset_id: "asset-1",
          media_type: "image/png",
          url: "https://example.com/image.png",
        },
      ],
    });
    const assistant = createMessage({
      id: "assistant-image",
      clientKey: "assistant-image",
      role: "assistant",
    });

    expect(resolveLastTurnActions([user, assistant], false)).toEqual({
      editableUserMessageId: null,
      regenerableAssistantMessageId: "assistant-image",
      assistantMetrics: null,
    });
  });

  it("hides all last-turn actions while streaming", () => {
    const user = createMessage({
      id: "user-streaming",
      clientKey: "user-streaming",
      role: "user",
    });
    const assistant = createMessage({
      id: "assistant-streaming",
      clientKey: "assistant-streaming",
      role: "assistant",
      status: "streaming",
    });

    expect(resolveLastTurnActions([user, assistant], true)).toEqual({
      editableUserMessageId: null,
      regenerableAssistantMessageId: null,
      assistantMetrics: null,
    });
  });
});
