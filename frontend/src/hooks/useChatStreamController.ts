import { useCallback, useEffect, useRef, useState } from "react";
import { cancelConversationMessage, streamChat } from "../services/api";
import {
  UNEXPECTED_STREAM_END_MESSAGE,
  cloneConversation,
  cloneMessage,
  cloneUpload,
  deriveTitle,
  describeError,
  hasSendableContent,
  isBusyPhase,
  isRetryableError,
  toDisplayMessage,
  type AppPhase,
  type DisplayConversation,
  type StreamRuntime,
} from "../features/chat/model";
import {
  appendOptimisticMessages,
  applyAssistantDelta,
  applyStreamMetaToMessages,
  buildPromotedDraftConversation,
  replaceAssistantMessage,
  settleAssistantMessages,
  type AssistantSettleUpdates,
  type StreamMetaPayload,
} from "../features/chat/streamLifecycle";
import { createStreamSession } from "../features/chat/streamSession";
import type { ComposerController } from "./useComposerController";
import type { ConversationController } from "./useConversationController";

type StreamControllerOptions = {
  composer: ComposerController;
  conversation: ConversationController;
};

export const useChatStreamController = ({
  composer,
  conversation,
}: StreamControllerOptions) => {
  const [phase, setPhase] = useState<AppPhase>("idle");

  const streamRuntimeRef = useRef<StreamRuntime | null>(null);
  const stopTimeoutRef = useRef<number | null>(null);

  const isBusy = isBusyPhase(phase);

  const clearStopTimeout = useCallback(() => {
    if (stopTimeoutRef.current !== null) {
      window.clearTimeout(stopTimeoutRef.current);
      stopTimeoutRef.current = null;
    }
  }, []);

  useEffect(
    () => () => {
      clearStopTimeout();
      streamRuntimeRef.current?.controller.abort();
    },
    [clearStopTimeout],
  );

  const finalizeStreamState = useCallback(
    (nextPhase: AppPhase) => {
      clearStopTimeout();
      streamRuntimeRef.current = null;
      setPhase(nextPhase);
    },
    [clearStopTimeout],
  );

  const settleAssistantMessage = useCallback(
    (runtime: StreamRuntime, updates: AssistantSettleUpdates) => {
      conversation.patchConversationMessages(runtime.currentConversationId, (messages) =>
        settleAssistantMessages(messages, runtime.assistantClientKey, updates),
      );
    },
    [conversation],
  );

  const restoreOptimisticSnapshot = useCallback(
    (runtime: StreamRuntime) => {
      if (runtime.originConversationId === null) {
        conversation.restoreDraftMessages(runtime.previousDraftMessages);
        return;
      }

      conversation.restoreConversationSnapshot(runtime.previousConversation);
    },
    [conversation],
  );

  const armStopRecovery = useCallback(
    (runtime: StreamRuntime) => {
      clearStopTimeout();
      stopTimeoutRef.current = window.setTimeout(() => {
        if (streamRuntimeRef.current !== runtime) {
          return;
        }

        runtime.controller.abort();
      }, 1800);
    },
    [clearStopTimeout],
  );

  const promoteDraftConversation = useCallback(
    (runtime: StreamRuntime, meta: StreamMetaPayload) => {
      const detail: DisplayConversation = buildPromotedDraftConversation(
        conversation.draftMessagesRef.current,
        runtime,
        meta,
      );

      conversation.setHistoryMotionSource("user");
      conversation.syncConversation(detail, true);
      conversation.setDraftMessages([]);
      conversation.setActiveConversationId(meta.conversationId);
      conversation.markConversationBorn(meta.conversationId);
    },
    [conversation],
  );

  const patchRuntimeMeta = useCallback(
    (runtime: StreamRuntime, meta: StreamMetaPayload) => {
      runtime.metaReceived = true;
      runtime.currentConversationId = meta.conversationId;
      runtime.userMessageId = meta.userMessageId;
      runtime.assistantMessageId = meta.assistantMessageId;

      if (runtime.originConversationId === null) {
        promoteDraftConversation(runtime, meta);
        return;
      }

      conversation.setConversationDetails((current) => {
        const detail = current[runtime.originConversationId as string];
        if (!detail) {
          return current;
        }

        return {
          ...current,
          [runtime.originConversationId as string]: {
            ...detail,
            title: meta.title || detail.title,
            messages: applyStreamMetaToMessages(detail.messages, runtime, meta),
          },
        };
      });
    },
    [conversation, promoteDraftConversation],
  );

  const handleStop = useCallback(async () => {
    const runtime = streamRuntimeRef.current;
    if (!runtime || runtime.stopRequested) {
      return;
    }

    runtime.stopRequested = true;
    setPhase("stopping");
    armStopRecovery(runtime);

    if (runtime.currentConversationId && runtime.assistantMessageId) {
      try {
        const cancelled = await cancelConversationMessage(
          runtime.currentConversationId,
          runtime.assistantMessageId,
        );
        if (streamRuntimeRef.current !== runtime) {
          return;
        }

        conversation.setHistoryMotionSource("stream");
        conversation.syncSummary(cancelled.conversation, true);
        conversation.setConversationDetails((current) => {
          const detail = current[runtime.currentConversationId as string];
          if (!detail) {
            return current;
          }

          return {
            ...current,
            [runtime.currentConversationId as string]: {
              ...detail,
              ...cancelled.conversation,
              messages: replaceAssistantMessage(detail.messages, runtime.assistantClientKey, {
                ...toDisplayMessage(cancelled.message),
                clientKey: runtime.assistantClientKey,
              }),
            },
          };
        });
      } catch {
        if (streamRuntimeRef.current !== runtime) {
          return;
        }

        runtime.controller.abort();
        if (runtime.currentConversationId) {
          void conversation.reconcileConversation(runtime.currentConversationId, true);
        } else {
          void conversation.refreshConversationList(conversation.activeConversationIdRef.current);
        }
      }
      return;
    }

    runtime.controller.abort();
    void conversation.refreshConversationList(conversation.activeConversationIdRef.current);
  }, [armStopRecovery, conversation]);

  useEffect(() => {
    if (!isBusy) {
      return undefined;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }

      event.preventDefault();
      void handleStop();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleStop, isBusy]);

  const sendPrompt = useCallback(async () => {
    if (isBusy) {
      return;
    }

    const trimmedInput = composer.input.trim();
    const snapshotUploads = composer.pendingUploadsRef.current.map(cloneUpload);
    if (!hasSendableContent(trimmedInput, snapshotUploads)) {
      return;
    }

    if (composer.hasUploadingUploads) {
      composer.setMotionSource("user");
      composer.setComposerError({
        message: "Wait for image uploads to finish.",
        retryable: false,
      });
      return;
    }

    if (composer.hasErroredUploads) {
      composer.setMotionSource("user");
      composer.setComposerError({
        message: "Retry or remove failed images before sending.",
        retryable: false,
      });
      return;
    }

    const currentConversationId = conversation.activeConversationIdRef.current;
    const previousDraftMessages = conversation.draftMessagesRef.current.map(cloneMessage);
    const previousConversation = currentConversationId
      ? cloneConversation(
          conversation.conversationDetailsRef.current[currentConversationId] ?? null,
        )
      : null;

    const { readyUploads, userMessage, assistantMessage, runtime, payload } =
      createStreamSession({
        currentConversationId,
        snapshotText: trimmedInput,
        snapshotUploads,
        previousDraftMessages,
        previousConversation,
      });

    conversation.patchConversationMessages(currentConversationId, (messages) =>
      appendOptimisticMessages(messages, userMessage, assistantMessage),
    );

    composer.clearComposerError();
    composer.setInput("");
    composer.setPendingUploads([]);
    composer.setMotionSource("user");
    conversation.closeMobileSidebar();
    conversation.clearDeleteConfirmation();
    conversation.setStickToBottom(true);
    conversation.setViewportMotionSource("stream");
    conversation.setHistoryMotionSource("stream");
    setPhase("streaming");

    streamRuntimeRef.current = runtime;

    try {
      for await (const event of streamChat(payload, runtime.controller.signal)) {
        if (
          event.event === "meta" &&
          event.conversation_id &&
          event.user_message_id &&
          event.assistant_message_id
        ) {
          patchRuntimeMeta(runtime, {
            conversationId: event.conversation_id,
            title: event.title || deriveTitle(trimmedInput, readyUploads.length),
            model: event.model,
            userMessageId: event.user_message_id,
            assistantMessageId: event.assistant_message_id,
          });
          continue;
        }

        if (event.event === "delta") {
          conversation.patchConversationMessages(runtime.currentConversationId, (messages) =>
            applyAssistantDelta(
              messages,
              runtime.assistantClientKey,
              event.delta || "",
              event.model,
            ),
          );
          continue;
        }

        if (event.event === "done" && event.message && event.conversation) {
          const finalAssistant = {
            ...toDisplayMessage(event.message),
            clientKey: runtime.assistantClientKey,
          };
          const targetConversationId = event.conversation.id;

          conversation.setConversationDetails((current) => {
            const detail = current[targetConversationId];
            if (!detail) {
              return current;
            }

            return {
              ...current,
              [targetConversationId]: {
                ...detail,
                ...event.conversation,
                messages: replaceAssistantMessage(
                  detail.messages,
                  runtime.assistantClientKey,
                  finalAssistant,
                ),
              },
            };
          });
          conversation.setHistoryMotionSource("stream");
          conversation.syncSummary(event.conversation, true);
          composer.releaseUploads(snapshotUploads, { deleteRemote: false });
          composer.clearComposerError();
          finalizeStreamState("idle");
          return;
        }

        if (event.event === "error") {
          if (!runtime.metaReceived) {
            restoreOptimisticSnapshot(runtime);
            composer.restoreComposerSnapshot(
              runtime.snapshotText,
              runtime.snapshotUploads,
            );
          } else {
            composer.setMotionSource("stream");
            composer.setInput(runtime.snapshotText);
            settleAssistantMessage(runtime, {
              status: "failed",
              error: event.error || "Service temporarily unavailable.",
              model: event.model,
            });
            if (runtime.currentConversationId) {
              void conversation.reconcileConversation(runtime.currentConversationId, true);
            }
            composer.releaseUploads(snapshotUploads, { deleteRemote: false });
          }

          composer.setMotionSource("stream");
          composer.setComposerError({
            message: event.error || "Service temporarily unavailable.",
            retryable: true,
          });
          finalizeStreamState("error");
          return;
        }
      }

      if (!runtime.metaReceived) {
        restoreOptimisticSnapshot(runtime);
        composer.restoreComposerSnapshot(runtime.snapshotText, runtime.snapshotUploads);
      } else {
        composer.setMotionSource("stream");
        settleAssistantMessage(runtime, {
          status: "failed",
          error: UNEXPECTED_STREAM_END_MESSAGE,
        });
        if (runtime.currentConversationId) {
          await conversation
            .reconcileConversation(runtime.currentConversationId, true)
            .catch(() => undefined);
        }
        composer.releaseUploads(snapshotUploads, { deleteRemote: false });
      }
      composer.setMotionSource("stream");
      composer.setComposerError({
        message: UNEXPECTED_STREAM_END_MESSAGE,
        retryable: true,
      });
      finalizeStreamState("error");
      return;
    } catch (error) {
      if (runtime.stopRequested) {
        if (!runtime.metaReceived) {
          restoreOptimisticSnapshot(runtime);
          composer.restoreComposerSnapshot(runtime.snapshotText, runtime.snapshotUploads);
          void conversation.refreshConversationList(
            conversation.activeConversationIdRef.current,
          );
        } else if (runtime.currentConversationId) {
          settleAssistantMessage(runtime, {
            status: "cancelled",
            finishReason: "cancelled",
          });
          await conversation
            .reconcileConversation(runtime.currentConversationId, true)
            .catch(() => undefined);
          composer.releaseUploads(snapshotUploads, { deleteRemote: false });
        }
        finalizeStreamState("idle");
        return;
      }

      const retryable = isRetryableError(error);
      const message = describeError(error, "Service temporarily unavailable.");

      if (!runtime.metaReceived) {
        restoreOptimisticSnapshot(runtime);
        composer.restoreComposerSnapshot(runtime.snapshotText, runtime.snapshotUploads);
      } else {
        composer.setMotionSource("stream");
        composer.setInput(runtime.snapshotText);
        settleAssistantMessage(runtime, {
          status: "failed",
          error: message,
        });
        if (runtime.currentConversationId) {
          await conversation
            .reconcileConversation(runtime.currentConversationId, true)
            .catch(() => undefined);
        }
        composer.releaseUploads(snapshotUploads, { deleteRemote: false });
      }

      composer.setMotionSource("stream");
      composer.setComposerError({
        message,
        retryable,
      });
      finalizeStreamState("error");
    } finally {
      composer.focusInput();
    }
  }, [
    composer,
    conversation,
    finalizeStreamState,
    isBusy,
    patchRuntimeMeta,
    restoreOptimisticSnapshot,
    settleAssistantMessage,
  ]);

  const handleRetry = useCallback(() => {
    if (isBusy || !composer.composerError?.retryable) {
      return;
    }

    void sendPrompt();
  }, [composer.composerError?.retryable, isBusy, sendPrompt]);

  const isMetaPendingDraft =
    conversation.isDraftSelected && isBusy && conversation.draftMessages.length > 0;

  return {
    phase,
    isBusy,
    isMetaPendingDraft,
    sendPrompt,
    handleStop,
    handleRetry,
  };
};

export type ChatStreamController = ReturnType<typeof useChatStreamController>;
