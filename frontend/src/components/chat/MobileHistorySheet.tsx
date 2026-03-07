import { useEffect, useId, useRef } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronLeft, Plus } from "lucide-react";
import {
  MOTION_SPRING,
  MOTION_TRANSITION,
  isUserDrivenMotion,
  shouldAnimateLayout,
  type MotionSource,
} from "../../motion/tokens";
import type { ConversationSummary } from "../../services/api";

type MobileHistorySheetProps = {
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  deleteConfirmId: string | null;
  isOpen: boolean;
  isBusy: boolean;
  isDraftSelected: boolean;
  isMetaPendingDraft: boolean;
  motionSource: MotionSource;
  onClose: () => void;
  onStartNewChat: () => void;
  onSelectConversation: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string) => void;
  onCancelDelete: () => void;
};

const MobileHistorySheet = ({
  conversations,
  activeConversationId,
  deleteConfirmId,
  isOpen,
  isBusy,
  isDraftSelected,
  isMetaPendingDraft,
  motionSource,
  onClose,
  onStartNewChat,
  onSelectConversation,
  onDeleteConversation,
  onCancelDelete,
}: MobileHistorySheetProps) => {
  const reduceMotion = useReducedMotion();
  const enableLayout = shouldAnimateLayout(motionSource);
  const enableSharedLayout = isUserDrivenMotion(motionSource);
  const dialogTitleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousActiveElementRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    const activeElement = document.activeElement;
    previousActiveElementRef.current = activeElement instanceof HTMLElement ? activeElement : null;
    document.body.style.overflow = "hidden";

    const frameId = window.requestAnimationFrame(() => {
      (closeButtonRef.current ?? panelRef.current)?.focus();
    });

    return () => {
      window.cancelAnimationFrame(frameId);
      document.body.style.overflow = previousOverflow;
      previousActiveElementRef.current?.focus();
      previousActiveElementRef.current = null;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const getFocusableElements = () => {
      const panel = panelRef.current;
      if (!panel) {
        return [] as HTMLElement[];
      }

      return Array.from(
        panel.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true");
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const focusable = getFocusableElements();
      if (focusable.length === 0) {
        event.preventDefault();
        panelRef.current?.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement;

      if (event.shiftKey) {
        if (activeElement === first || activeElement === panelRef.current) {
          event.preventDefault();
          last.focus();
        }
        return;
      }

      if (activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  return (
    <AnimatePresence>
      {isOpen ? (
        <>
          <motion.div
            key="mobile-history-backdrop"
            className="fixed inset-0 z-30 bg-black/72 md:hidden"
            aria-hidden="true"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={MOTION_TRANSITION.fade}
          />
          <motion.div
            key="mobile-history-sheet"
            className="mobile-sheet fixed inset-x-0 bottom-0 z-40 md:hidden"
            role="dialog"
            aria-modal="true"
            aria-labelledby={dialogTitleId}
            tabIndex={-1}
            ref={panelRef}
            initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 42, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 36, scale: 0.992 }}
            transition={reduceMotion ? MOTION_TRANSITION.fade : MOTION_SPRING.sheet}
          >
            <motion.div
              className="mx-auto flex h-full max-h-[65vh] flex-col rounded-t-[1.9rem] border border-white/10 border-b-0 bg-[#0a0b0d]/95 px-5 pb-6 pt-4 backdrop-blur-xl"
              initial="hidden"
              animate="visible"
              exit="hidden"
              variants={{
                hidden: {},
                visible: {
                  transition: {
                    staggerChildren: reduceMotion ? 0 : 0.03,
                    delayChildren: reduceMotion ? 0 : 0.02,
                  },
                },
              }}
            >
              <h2 id={dialogTitleId} className="sr-only">
                Conversation history
              </h2>
              <motion.div
                className="mb-4 flex items-center justify-between"
                variants={{
                  hidden: { opacity: 0, y: 8 },
                  visible: { opacity: 1, y: 0 },
                }}
                transition={MOTION_TRANSITION.soft}
              >
                <div className="mx-auto h-1 w-12 rounded-full bg-white/10" />
                <button
                  ref={closeButtonRef}
                  type="button"
                  aria-label="Close history"
                  className="sidebar-collapse-trigger absolute right-4 top-3"
                  onClick={onClose}
                >
                  <ChevronLeft className="h-4 w-4 -rotate-90" strokeWidth={1.8} />
                </button>
              </motion.div>

              <motion.button
                type="button"
                layout={enableLayout ? "position" : false}
                layoutId={enableSharedLayout && isMetaPendingDraft ? "new-chat-anchor" : undefined}
                className={`mb-5 flex items-center gap-3 py-2 text-left text-sm transition ${
                  isDraftSelected ? "text-white" : "text-zinc-200 hover:text-white"
                } disabled:cursor-not-allowed disabled:opacity-40`}
                onClick={onStartNewChat}
                disabled={isBusy}
                variants={{
                  hidden: { opacity: 0, y: 8 },
                  visible: { opacity: 1, y: 0 },
                }}
                transition={MOTION_TRANSITION.enter}
              >
                <Plus className="h-4 w-4" strokeWidth={1.8} />
                <span>New chat</span>
              </motion.button>

              <motion.nav
                aria-label="Conversation history"
                className="space-y-1 overflow-y-auto pb-2 pr-1"
                variants={{
                  hidden: { opacity: 0, y: 8 },
                  visible: { opacity: 1, y: 0 },
                }}
                transition={MOTION_TRANSITION.enter}
              >
                {conversations.map((conversation) => {
                  const isActive = conversation.id === activeConversationId;
                  const isConfirming = deleteConfirmId === conversation.id;

                  return (
                    <motion.div
                      key={conversation.id}
                      layout={enableLayout ? "position" : false}
                      className="history-row group flex items-start justify-between gap-3 rounded-[1rem] px-2"
                      transition={MOTION_SPRING.list}
                    >
                      <button
                        type="button"
                        className={`block min-w-0 flex-1 truncate py-2 text-left text-sm transition ${
                          isActive ? "text-white" : "text-zinc-500 hover:text-zinc-200"
                        } disabled:cursor-not-allowed disabled:opacity-40`}
                        onClick={() => onSelectConversation(conversation.id)}
                        disabled={isBusy}
                      >
                        {conversation.title}
                      </button>
                      {isConfirming ? (
                        <div className="flex shrink-0 items-center gap-2 pt-1">
                          <button
                            type="button"
                            className="history-item-delete text-white opacity-100"
                            onClick={() => onDeleteConversation(conversation.id)}
                          >
                            Confirm
                          </button>
                          <button
                            type="button"
                            className="history-item-delete opacity-100"
                            onClick={onCancelDelete}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="history-item-delete shrink-0 pt-1 opacity-100"
                          onClick={() => onDeleteConversation(conversation.id)}
                          disabled={isBusy}
                        >
                          Delete
                        </button>
                      )}
                    </motion.div>
                  );
                })}
              </motion.nav>
            </motion.div>
          </motion.div>
        </>
      ) : null}
    </AnimatePresence>
  );
};

export default MobileHistorySheet;
