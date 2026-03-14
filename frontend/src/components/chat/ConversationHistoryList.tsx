import { useEffect, useRef, useState } from "react";
import { groupConversationsByUpdatedAt, normalizeConversationTitle } from "../../features/chat/historyGroups";
import type { ConversationSummary } from "../../services/api";

type ConversationHistoryListProps = {
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  isBusy: boolean;
  menuVisibility: "hover" | "always";
  onSelectConversation: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string) => void;
  onRenameConversation: (conversationId: string, title: string) => Promise<void> | void;
};

const ConversationHistoryList = ({
  conversations,
  activeConversationId,
  isBusy,
  menuVisibility,
  onSelectConversation,
  onDeleteConversation,
  onRenameConversation,
}: ConversationHistoryListProps) => {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [renamingConversationId, setRenamingConversationId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [isSavingRename, setIsSavingRename] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!openMenuId) {
      return undefined;
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpenMenuId(null);
      }
    };

    window.addEventListener("pointerdown", handlePointerDown);
    return () => window.removeEventListener("pointerdown", handlePointerDown);
  }, [openMenuId]);

  useEffect(() => {
    if (!isBusy) {
      return;
    }

    setOpenMenuId(null);
    setRenamingConversationId(null);
    setRenameDraft("");
    setIsSavingRename(false);
  }, [isBusy]);

  const cancelRename = () => {
    if (isSavingRename) {
      return;
    }

    setRenamingConversationId(null);
    setRenameDraft("");
  };

  const beginRename = (conversation: ConversationSummary) => {
    if (isBusy) {
      return;
    }

    setOpenMenuId(null);
    setRenamingConversationId(conversation.id);
    setRenameDraft(conversation.title);
  };

  const submitRename = async (conversation: ConversationSummary) => {
    const normalizedTitle = normalizeConversationTitle(renameDraft);
    if (!normalizedTitle || normalizedTitle === conversation.title) {
      cancelRename();
      return;
    }

    setIsSavingRename(true);
    try {
      await onRenameConversation(conversation.id, normalizedTitle);
      setRenamingConversationId(null);
      setRenameDraft("");
    } catch {
      // Keep the inline field open so the user can adjust the title.
    } finally {
      setIsSavingRename(false);
    }
  };

  const groups = groupConversationsByUpdatedAt(conversations);

  return (
    <div ref={rootRef} className="space-y-5">
      {groups.map((group) => (
        <section key={group.label} aria-label={group.label} className="space-y-1.5">
          <div className="history-group-label">{group.label}</div>
          <div className="space-y-1">
            {group.items.map((conversation) => {
              const isActive = conversation.id === activeConversationId;
              const isRenaming = renamingConversationId === conversation.id;
              const isMenuOpen = openMenuId === conversation.id;

              return (
                <div
                  key={conversation.id}
                  className={`history-item-shell group ${isActive ? "is-active" : ""}`}
                >
                  {isRenaming ? (
                    <input
                      type="text"
                      aria-label="Rename conversation"
                      className="history-rename-input"
                      value={renameDraft}
                      maxLength={80}
                      autoFocus
                      onBlur={cancelRename}
                      onChange={(event) => setRenameDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Escape") {
                          event.preventDefault();
                          cancelRename();
                          return;
                        }

                        if (event.key === "Enter") {
                          event.preventDefault();
                          void submitRename(conversation);
                        }
                      }}
                    />
                  ) : (
                    <button
                      type="button"
                      className="history-item-trigger"
                      onClick={() => onSelectConversation(conversation.id)}
                      disabled={isBusy}
                    >
                      <span className="truncate">{conversation.title}</span>
                    </button>
                  )}

                  <div className="history-item-menu-shell">
                    <button
                      type="button"
                      aria-label={`Open actions for ${conversation.title}`}
                      className={`history-item-menu-trigger ${
                        menuVisibility === "always" ? "is-always-visible" : ""
                      }`}
                      aria-expanded={isMenuOpen}
                      disabled={isBusy || isRenaming}
                      onClick={() =>
                        setOpenMenuId((current) =>
                          current === conversation.id ? null : conversation.id,
                        )
                      }
                    >
                      <span aria-hidden="true">⋯</span>
                    </button>

                    {isMenuOpen ? (
                      <div className="history-item-menu" role="menu" aria-label={`${conversation.title} actions`}>
                        <button
                          type="button"
                          role="menuitem"
                          className="history-item-menu-action"
                          onClick={() => beginRename(conversation)}
                        >
                          Rename
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          className="history-item-menu-action is-danger"
                          onClick={() => {
                            setOpenMenuId(null);
                            onDeleteConversation(conversation.id);
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
};

export default ConversationHistoryList;
