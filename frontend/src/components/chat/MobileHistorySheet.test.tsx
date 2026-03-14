import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import MobileHistorySheet from "./MobileHistorySheet";

const conversations = [
  {
    id: "conversation-1",
    title: "Alpha",
    updated_at: "2026-03-07T12:00:00.000Z",
    created_at: "2026-03-07T12:00:00.000Z",
    last_message_preview: "Hi",
    message_count: 2,
  },
];

const renderHarness = (options?: { onClose?: () => void }) => {
  const onClose = options?.onClose ?? vi.fn();

  const Harness = () => {
    const [isOpen, setIsOpen] = useState(false);

    return (
      <>
        <button type="button" onClick={() => setIsOpen(true)}>
          Launcher
        </button>
        <MobileHistorySheet
          conversations={conversations}
          activeConversationId={conversations[0].id}
          isOpen={isOpen}
          isBusy={false}
          isDraftSelected={false}
          isMetaPendingDraft={false}
          motionSource="user"
          onClose={() => {
            onClose();
            setIsOpen(false);
          }}
          onStartNewChat={() => undefined}
          onSelectConversation={() => undefined}
          onDeleteConversation={() => undefined}
          onRenameConversation={() => undefined}
        />
      </>
    );
  };

  render(<Harness />);
  return {
    onClose,
    launcher: screen.getByRole("button", { name: "Launcher" }),
  };
};

describe("MobileHistorySheet", () => {
  it("acts like a dialog, locks background scroll, and closes on Escape", async () => {
    const user = userEvent.setup();
    const { onClose, launcher } = renderHarness();

    launcher.focus();
    await user.click(launcher);
    const dialog = await screen.findByRole("dialog", { name: /conversation history/i });
    const closeButton = screen.getByRole("button", { name: /close history/i });

    await waitFor(() => expect(closeButton).toHaveFocus());
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(document.body.style.overflow).toBe("");
    expect(launcher).toHaveFocus();
  });

  it("keeps keyboard focus trapped inside the sheet", async () => {
    const user = userEvent.setup();
    const { launcher } = renderHarness();
    await user.click(launcher);

    const closeButton = screen.getByRole("button", { name: /close history/i });
    const actionsButton = screen.getByRole("button", { name: /open actions for alpha/i });

    await waitFor(() => expect(closeButton).toHaveFocus());

    await user.tab({ shift: true });
    expect(actionsButton).toHaveFocus();

    await user.tab();
    expect(closeButton).toHaveFocus();
  });
});
