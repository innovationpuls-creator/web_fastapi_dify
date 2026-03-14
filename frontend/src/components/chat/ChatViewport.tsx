import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import ConversationMessage from "../ConversationMessage";
import {
  MOTION_SPRING,
  MOTION_TRANSITION,
  getSceneTransition,
  shouldAnimateLayout,
  type MotionSource,
} from "../../motion/tokens";
import {
  type AppPhase,
  type DisplayConversation,
  type ScreenError,
  getMessageText,
  type DisplayMessage,
} from "../../features/chat/model";
import { resolveLastTurnActions } from "../../features/chat/turnActions";

type ChatViewportProps = {
  viewportRef: React.RefObject<HTMLDivElement>;
  currentMessages: DisplayMessage[];
  activeConversationId: string | null;
  activeConversation: DisplayConversation | null;
  loadingConversationId: string | null;
  screenError: ScreenError | null;
  phase: AppPhase;
  sceneKey: number;
  motionSource: MotionSource;
  onScroll: () => void;
  onRetryScreen: () => void;
  onEditMessage: (messageId: string) => void;
  onRegenerateMessage: (messageId: string) => void;
};

const stateVariants = {
  hidden: { opacity: 0, y: 12, scale: 0.992 },
  visible: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -8, scale: 0.992 },
};

const ChatViewport = ({
  viewportRef,
  currentMessages,
  activeConversationId,
  activeConversation,
  loadingConversationId,
  screenError,
  phase,
  sceneKey,
  motionSource,
  onScroll,
  onRetryScreen,
  onEditMessage,
  onRegenerateMessage,
}: ChatViewportProps) => {
  const reduceMotion = useReducedMotion();
  const isConversationLoading =
    loadingConversationId !== null &&
    loadingConversationId === activeConversationId &&
    !activeConversation;
  const sceneTransition = getSceneTransition(motionSource, Boolean(reduceMotion));
  const shouldLayoutRows = shouldAnimateLayout(motionSource);
  const lastTurnActions = resolveLastTurnActions(
    currentMessages,
    phase === "streaming" || phase === "stopping",
  );

  return (
    <div ref={viewportRef} className="flex-1 overflow-y-auto" onScroll={onScroll}>
      <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-5 pb-52 pt-10 sm:px-8 sm:pt-14">
        <AnimatePresence initial={false} mode="wait">
          {screenError ? (
            <motion.div
              key="screen-error"
              className="flex flex-1 flex-col items-center justify-center gap-4 pb-24 text-center"
              initial={reduceMotion ? { opacity: 0 } : stateVariants.hidden}
              animate={stateVariants.visible}
              exit={reduceMotion ? { opacity: 0 } : stateVariants.exit}
              transition={MOTION_TRANSITION.enter}
            >
              <div className="text-sm tracking-[0.24em] text-zinc-500">{screenError.message}</div>
              <button
                type="button"
                className="text-[11px] uppercase tracking-[0.28em] text-zinc-400 transition hover:text-white"
                onClick={onRetryScreen}
              >
                Retry
              </button>
            </motion.div>
          ) : isConversationLoading ? (
            <motion.div
              key="loading"
              className="flex flex-1 items-center justify-center pb-24 text-sm tracking-[0.28em] text-zinc-700"
              initial={reduceMotion ? { opacity: 0 } : stateVariants.hidden}
              animate={stateVariants.visible}
              exit={reduceMotion ? { opacity: 0 } : stateVariants.exit}
              transition={MOTION_TRANSITION.fade}
            >
              Loading
            </motion.div>
          ) : currentMessages.length === 0 ? (
            <motion.div
              key="empty"
              className="flex flex-1 items-center justify-center pb-24 text-sm tracking-[0.28em] text-zinc-700"
              initial={reduceMotion ? { opacity: 0 } : stateVariants.hidden}
              animate={stateVariants.visible}
              exit={reduceMotion ? { opacity: 0 } : stateVariants.exit}
              transition={MOTION_TRANSITION.fade}
            >
              AI
            </motion.div>
          ) : (
            <motion.div
              key={`chat-scene-${sceneKey}`}
              className="flex flex-col gap-8"
              initial={
                motionSource === "user" && !reduceMotion
                  ? { opacity: 0, y: 18, scale: 0.996 }
                  : { opacity: 0 }
              }
              animate={{ opacity: 1, y: 0 }}
              exit={motionSource === "user" && !reduceMotion ? { opacity: 0, y: -10 } : { opacity: 0 }}
              transition={sceneTransition}
            >
              {currentMessages.map((message, index) => {
                const isStreamingMessage =
                  (phase === "streaming" || phase === "stopping") &&
                  index === currentMessages.length - 1 &&
                  message.role === "assistant";
                const previousMessage = index > 0 ? currentMessages[index - 1] : undefined;

                return (
                  <motion.div
                    key={message.clientKey}
                    layout={shouldLayoutRows ? "position" : false}
                    className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                    initial={
                      reduceMotion
                        ? { opacity: 0 }
                        : motionSource === "system"
                          ? { opacity: 0 }
                          : { opacity: 0, y: message.role === "user" ? 18 : 12, scale: 0.992 }
                    }
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    transition={motionSource === "user" ? MOTION_SPRING.bubble : MOTION_TRANSITION.soft}
                  >
                    <ConversationMessage
                      message={message}
                      isStreaming={isStreamingMessage}
                      previousUserText={previousMessage?.role === "user" ? getMessageText(previousMessage) : ""}
                      showEdit={message.id === lastTurnActions.editableUserMessageId}
                      showRegenerate={message.id === lastTurnActions.regenerableAssistantMessageId}
                      onEdit={() => onEditMessage(message.id)}
                      onRegenerate={() => onRegenerateMessage(message.id)}
                    />
                  </motion.div>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default ChatViewport;
