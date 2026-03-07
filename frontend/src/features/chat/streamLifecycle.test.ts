import { describe, expect, it } from "vitest";
import {
  applyAssistantDelta,
  applyStreamMetaToMessages,
  replaceAssistantMessage,
  settleAssistantMessages,
} from "./streamLifecycle";
import { getMessageText, type DisplayMessage } from "./model";

const baseTimestamp = "2026-03-07T12:00:00.000Z";

const createMessage = (overrides: Partial<DisplayMessage>): DisplayMessage => ({
  clientKey: overrides.clientKey ?? overrides.id ?? "message-1",
  id: overrides.id ?? "message-1",
  conversation_id: overrides.conversation_id ?? "conversation-1",
  role: overrides.role ?? "assistant",
  status: overrides.status ?? "completed",
  parts: overrides.parts ?? [{ type: "text", text: "Hello" }],
  created_at: overrides.created_at ?? baseTimestamp,
  updated_at: overrides.updated_at ?? baseTimestamp,
  model: overrides.model ?? null,
  finish_reason: overrides.finish_reason ?? null,
  error: overrides.error ?? null,
  isSkeleton: overrides.isSkeleton,
});

describe("streamLifecycle", () => {
  it("updates only the targeted assistant message when applying deltas", () => {
    const userMessage = createMessage({
      clientKey: "user-1",
      id: "user-1",
      role: "user",
      parts: [{ type: "text", text: "Hi" }],
    });
    const assistantMessage = createMessage({
      clientKey: "assistant-1",
      id: "assistant-1",
      role: "assistant",
      parts: [{ type: "text", text: "Hello" }],
      status: "streaming",
    });

    const nextMessages = applyAssistantDelta(
      [userMessage, assistantMessage],
      assistantMessage.clientKey,
      " world",
      "demo-model",
    );

    expect(nextMessages[0]).toBe(userMessage);
    expect(nextMessages[1]).not.toBe(assistantMessage);
    expect(getMessageText(nextMessages[1])).toBe("Hello world");
    expect(nextMessages[1].model).toBe("demo-model");
    expect(nextMessages[1].status).toBe("streaming");
  });

  it("replaces and settles assistant messages without recreating unrelated rows", () => {
    const userMessage = createMessage({
      clientKey: "user-2",
      id: "user-2",
      role: "user",
      parts: [{ type: "text", text: "Explain this" }],
    });
    const assistantMessage = createMessage({
      clientKey: "assistant-2",
      id: "assistant-2",
      role: "assistant",
      parts: [{ type: "text", text: "Draft" }],
      status: "streaming",
      isSkeleton: true,
    });
    const replacement = createMessage({
      clientKey: assistantMessage.clientKey,
      id: "assistant-final",
      role: "assistant",
      parts: [{ type: "text", text: "Final answer" }],
      model: "demo-model",
    });

    const replaced = replaceAssistantMessage(
      [userMessage, assistantMessage],
      assistantMessage.clientKey,
      replacement,
    );
    const settled = settleAssistantMessages(replaced, assistantMessage.clientKey, {
      status: "failed",
      error: "Network issue",
      finishReason: "error",
      model: "demo-model",
    });

    expect(replaced[0]).toBe(userMessage);
    expect(replaced[1]).toBe(replacement);
    expect(settled[0]).toBe(userMessage);
    expect(settled[1].status).toBe("failed");
    expect(settled[1].error).toBe("Network issue");
    expect(settled[1].finish_reason).toBe("error");
    expect(settled[1].isSkeleton).toBe(false);
  });

  it("applies stream metadata to the optimistic user and assistant pair", () => {
    const userMessage = createMessage({
      clientKey: "user-local",
      id: "user-local",
      role: "user",
      parts: [{ type: "text", text: "Hello" }],
    });
    const assistantMessage = createMessage({
      clientKey: "assistant-local",
      id: "assistant-local",
      role: "assistant",
      parts: [{ type: "text", text: "Draft" }],
      status: "streaming",
    });

    const nextMessages = applyStreamMetaToMessages(
      [userMessage, assistantMessage],
      {
        controller: new AbortController(),
        originConversationId: null,
        currentConversationId: null,
        userClientKey: userMessage.clientKey,
        assistantClientKey: assistantMessage.clientKey,
        userMessageId: userMessage.id,
        assistantMessageId: assistantMessage.id,
        snapshotText: "Hello",
        snapshotUploads: [],
        previousDraftMessages: [],
        previousConversation: null,
        metaReceived: false,
        stopRequested: false,
      },
      {
        conversationId: "conversation-42",
        title: "Hello",
        model: "demo-model",
        userMessageId: "user-remote",
        assistantMessageId: "assistant-remote",
      },
    );

    expect(nextMessages[0].conversation_id).toBe("conversation-42");
    expect(nextMessages[0].id).toBe("user-remote");
    expect(nextMessages[1].conversation_id).toBe("conversation-42");
    expect(nextMessages[1].id).toBe("assistant-remote");
    expect(nextMessages[1].model).toBe("demo-model");
  });
});
