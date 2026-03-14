import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ConversationHistoryList from "./ConversationHistoryList";
import type { ConversationSummary } from "../../services/api";

const conversations: ConversationSummary[] = [
  {
    id: "conversation-1",
    title: "Kant and reason",
    updated_at: "2026-03-14T11:00:00.000+08:00",
    created_at: "2026-03-14T11:00:00.000+08:00",
    last_message_preview: "Hi",
    message_count: 2,
  },
];

describe("ConversationHistoryList", () => {
  it("supports inline rename save and cancel interactions", async () => {
    const user = userEvent.setup();
    const onRenameConversation = vi.fn().mockResolvedValue(undefined);

    render(
      <ConversationHistoryList
        conversations={conversations}
        activeConversationId={conversations[0].id}
        isBusy={false}
        menuVisibility="always"
        onSelectConversation={() => undefined}
        onDeleteConversation={() => undefined}
        onRenameConversation={onRenameConversation}
      />,
    );

    await user.click(screen.getByRole("button", { name: /open actions for kant and reason/i }));
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));

    const input = screen.getByRole("textbox", { name: /rename conversation/i });
    await user.clear(input);
    await user.type(input, "Kant and duty{Enter}");

    await waitFor(() =>
      expect(onRenameConversation).toHaveBeenCalledWith("conversation-1", "Kant and duty"),
    );
    expect(screen.queryByRole("textbox", { name: /rename conversation/i })).not.toBeInTheDocument();
  });

  it("cancels inline rename on Escape", async () => {
    const user = userEvent.setup();
    const onRenameConversation = vi.fn();

    render(
      <ConversationHistoryList
        conversations={conversations}
        activeConversationId={conversations[0].id}
        isBusy={false}
        menuVisibility="always"
        onSelectConversation={() => undefined}
        onDeleteConversation={() => undefined}
        onRenameConversation={onRenameConversation}
      />,
    );

    await user.click(screen.getByRole("button", { name: /open actions for kant and reason/i }));
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: /rename conversation/i });

    await user.type(input, "{Escape}");

    expect(onRenameConversation).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox", { name: /rename conversation/i })).not.toBeInTheDocument();
  });
});
