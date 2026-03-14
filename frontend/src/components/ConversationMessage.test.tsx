import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ConversationMessage from "./ConversationMessage";
import type { DisplayMessage } from "../features/chat/model";
import { formatThoughtSummary } from "./conversationMessageUtils";

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
  thinking_completed_at: overrides.thinking_completed_at ?? null,
  model: overrides.model ?? "gpt-test",
  finish_reason: overrides.finish_reason ?? null,
  error: overrides.error ?? null,
  metrics: overrides.metrics ?? null,
  isSkeleton: overrides.isSkeleton,
});

describe("ConversationMessage", () => {
  it("uses thinking completion time instead of final answer time", () => {
    expect(
      formatThoughtSummary(
        "2026-03-07T12:00:00.000Z",
        "2026-03-07T12:00:10.000Z",
        "2026-03-07T12:00:03.000Z",
        false,
      ),
    ).toBe("Thought for 3 seconds");
  });

  it("renders assistant metrics footer and regenerate action", async () => {
    const user = userEvent.setup();
    const onRegenerate = vi.fn();

    render(
      <ConversationMessage
        message={createMessage({
          id: "assistant-last",
          clientKey: "assistant-last",
          role: "assistant",
          parts: [{ type: "text", text: "## Updated plan" }],
          metrics: {
            input_tokens: 120,
            output_tokens: 222,
            total_tokens: 342,
            latency_ms: 1200,
          },
        })}
        isStreaming={false}
        onRegenerate={onRegenerate}
        showRegenerate
      />,
    );

    expect(await screen.findByText("Tokens: 342")).toBeInTheDocument();
    expect(screen.getByText("Latency: 1.2s")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /regenerate/i }));
    expect(onRegenerate).toHaveBeenCalledTimes(1);
  });

  it("renders the edit action for the latest user message", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();

    render(
      <ConversationMessage
        message={createMessage({
          id: "user-last",
          clientKey: "user-last",
          role: "user",
          parts: [{ type: "text", text: "Please refine this section." }],
          model: null,
        })}
        isStreaming={false}
        onEdit={onEdit}
        showEdit
      />,
    );

    await user.click(screen.getByRole("button", { name: /edit message/i }));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });
});
