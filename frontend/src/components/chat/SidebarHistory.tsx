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
import ConversationHistoryList from "./ConversationHistoryList";

type SidebarHistoryProps = {
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  sidebarCollapsed: boolean;
  isBusy: boolean;
  isDraftSelected: boolean;
  isMetaPendingDraft: boolean;
  motionSource: MotionSource;
  onToggleCollapse: () => void;
  onStartNewChat: () => void;
  onSelectConversation: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string) => void;
  onRenameConversation: (conversationId: string, title: string) => Promise<void> | void;
};

const SidebarHistory = ({
  conversations,
  activeConversationId,
  sidebarCollapsed,
  isBusy,
  isDraftSelected,
  isMetaPendingDraft,
  motionSource,
  onToggleCollapse,
  onStartNewChat,
  onSelectConversation,
  onDeleteConversation,
  onRenameConversation,
}: SidebarHistoryProps) => {
  const reduceMotion = useReducedMotion();
  const panelTransition = reduceMotion ? MOTION_TRANSITION.soft : MOTION_SPRING.panel;
  const enableLayout = shouldAnimateLayout(motionSource);
  const enableSharedLayout = isUserDrivenMotion(motionSource);

  return (
    <>
      <aside className="desktop-sidebar fixed inset-y-0 left-0 z-30 hidden overflow-hidden border-r border-white/10 bg-[#08090b] md:flex">
        <motion.div
          className={`sidebar-panel flex min-h-screen w-[220px] min-w-[220px] flex-col px-5 py-4 ${
            sidebarCollapsed ? "pointer-events-none" : ""
          }`}
          initial={false}
          animate={{
            opacity: sidebarCollapsed ? 0 : 1,
            x: sidebarCollapsed ? -18 : 0,
            scale: sidebarCollapsed ? 0.98 : 1,
          }}
          transition={panelTransition}
        >
          <div className="mb-5 flex justify-end">
            <motion.button
              type="button"
              aria-label="Collapse sidebar"
              className="sidebar-collapse-trigger"
              onClick={onToggleCollapse}
              whileTap={reduceMotion ? undefined : { scale: 0.94 }}
            >
              <ChevronLeft className="h-4 w-4" strokeWidth={1.8} />
            </motion.button>
          </div>

          <motion.button
            type="button"
            layout={enableLayout ? "position" : false}
            layoutId={enableSharedLayout && isMetaPendingDraft ? "new-chat-anchor" : undefined}
            className={`mb-6 flex items-center gap-3 py-2 text-left text-sm transition ${
              isDraftSelected ? "text-white" : "text-zinc-200 hover:text-white"
            } disabled:cursor-not-allowed disabled:opacity-40`}
            onClick={onStartNewChat}
            disabled={isBusy}
            whileHover={reduceMotion ? undefined : { x: 2 }}
            whileTap={reduceMotion ? undefined : { scale: 0.985 }}
            transition={MOTION_TRANSITION.soft}
          >
            <Plus className="h-4 w-4" strokeWidth={1.8} />
            <span>New chat</span>
          </motion.button>

          <motion.nav
            aria-label="Conversation history"
            className="overflow-y-auto pr-1"
            layout={enableLayout ? "position" : false}
          >
            <ConversationHistoryList
              conversations={conversations}
              activeConversationId={activeConversationId}
              isBusy={isBusy}
              menuVisibility="hover"
              onSelectConversation={onSelectConversation}
              onDeleteConversation={onDeleteConversation}
              onRenameConversation={onRenameConversation}
            />
          </motion.nav>
        </motion.div>
      </aside>

      <AnimatePresence>
        {sidebarCollapsed ? (
          <motion.button
            key="floating-sidebar-toggle"
            type="button"
            aria-label="Expand sidebar"
            className="floating-sidebar-toggle fixed left-4 top-4 z-40 hidden gap-2 rounded-full border border-white/10 bg-[#0d1016]/92 px-3.5 text-[11px] font-medium uppercase tracking-[0.18em] text-zinc-200 shadow-[0_14px_36px_rgba(0,0,0,0.32)] backdrop-blur md:inline-flex"
            onClick={onToggleCollapse}
            initial={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.9, x: -10 }}
            animate={{ opacity: 1, scale: 1, x: 0 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.92, x: -8 }}
            transition={panelTransition}
            whileTap={reduceMotion ? undefined : { scale: 0.94 }}
          >
            <ChevronLeft className="h-4 w-4 rotate-180" strokeWidth={1.8} />
            <span>History</span>
          </motion.button>
        ) : null}
      </AnimatePresence>
    </>
  );
};

export default SidebarHistory;
