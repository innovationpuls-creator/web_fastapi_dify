import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelConversationMessage,
  editConversationMessageStream,
  regenerateConversationMessageStream,
  streamChat,
  type ChatProvider,
} from "../services/api";
import {
  DEFAULT_GENERATION,
  UNEXPECTED_STREAM_END_MESSAGE,
  cloneConversation,
  cloneMessage,
  cloneUpload,
  deriveTitle,
  describeError,
  hasSendableContent,
  isBusyPhase,
  nowIso,
  isRetryableError,
  toDisplayMessage,
  type AppPhase,
  type DisplayConversation,
  type DisplayMessage,
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
import { isPureTextUserMessage, resolveLastTurn } from "../features/chat/turnActions";
import type { ComposerController } from "./useComposerController";
import type { ConversationController } from "./useConversationController";

type StreamControllerOptions = {
  composer: ComposerController;
  conversation: ConversationController;
  provider: ChatProvider;
};

const restartAssistantMessageLocally = (message: DisplayMessage): DisplayMessage => {
  const updatedAt = nowIso();
  return {
    ...message,
    status: "streaming",
    parts: [],
    created_at: updatedAt,
    updated_at: updatedAt,
    thinking_completed_at: null,
    finish_reason: null,
    error: null,
    metrics: null,
    isSkeleton: true,
  };
};

const rewriteUserMessageLocally = (message: DisplayMessage, text: string): DisplayMessage => {
  const updatedAt = nowIso();
  return {
    ...message,
    parts: [{ type: "text", text }],
    updated_at: updatedAt,
  };
};

export const useChatStreamController = ({
  composer,
  conversation,
  provider,
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

  const runExistingTurnStream = useCallback(
    async ({
      conversationId,
      userMessage,
      assistantMessage,
      snapshotText,
      optimisticUpdater,
      streamFactory,
      restoreComposerOnNoMeta,
    }: {
      conversationId: string;
      userMessage: DisplayMessage;
      assistantMessage: DisplayMessage;
      snapshotText: string;
      optimisticUpdater: (messages: DisplayMessage[]) => DisplayMessage[];
      streamFactory: (
        signal: AbortSignal,
      ) => AsyncGenerator<import("../services/api").ChatStreamEvent, void, void>;
      restoreComposerOnNoMeta?: () => void;
    }) => {
      const previousConversation = cloneConversation(
        conversation.conversationDetailsRef.current[conversationId] ?? null,
      );
      if (!previousConversation) {
        return;
      }

      const runtime: StreamRuntime = {
        controller: new AbortController(),
        originConversationId: conversationId,
        currentConversationId: conversationId,
        userClientKey: userMessage.clientKey,
        assistantClientKey: assistantMessage.clientKey,
        userMessageId: userMessage.id,
        assistantMessageId: assistantMessage.id,
        snapshotText,
        snapshotUploads: [],
        previousDraftMessages: [],
        previousConversation,
        metaReceived: false,
        stopRequested: false,
      };

      conversation.patchConversationMessages(conversationId, optimisticUpdater);
      composer.clearComposerError();
      composer.setMotionSource("user");
      conversation.closeMobileSidebar();
      conversation.setStickToBottom(true);
      conversation.setViewportMotionSource("stream");
      conversation.setHistoryMotionSource("stream");
      setPhase("streaming");
      streamRuntimeRef.current = runtime;

      try {
        for await (const event of streamFactory(runtime.controller.signal)) {
          if (
            event.event === "meta" &&
            event.conversation_id &&
            event.user_message_id &&
            event.assistant_message_id
          ) {
            patchRuntimeMeta(runtime, {
              conversationId: event.conversation_id,
              title: event.title || previousConversation.title,
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
            const finalConversation = event.conversation;

            conversation.setConversationDetails((current) => {
              const detail = current[finalConversation.id];
              if (!detail) {
                return current;
              }

              return {
                ...current,
                [finalConversation.id]: {
                  ...detail,
                  ...finalConversation,
                  messages: replaceAssistantMessage(
                    detail.messages,
                    runtime.assistantClientKey,
                    finalAssistant,
                  ),
                },
              };
            });
            conversation.setHistoryMotionSource("stream");
            conversation.syncSummary(finalConversation, true);
            composer.clearComposerError();
            finalizeStreamState("idle");
            return;
          }

          if (event.event === "error") {
            if (!runtime.metaReceived) {
              restoreOptimisticSnapshot(runtime);
              restoreComposerOnNoMeta?.();
            } else {
              settleAssistantMessage(runtime, {
                status: "failed",
                error: event.error || "Service temporarily unavailable.",
                model: event.model,
              });
              if (runtime.currentConversationId) {
                void conversation.reconcileConversation(runtime.currentConversationId, true);
              }
            }

            composer.setMotionSource("stream");
            composer.setComposerError({
              message: event.error || "Service temporarily unavailable.",
              retryable: false,
            });
            finalizeStreamState("error");
            return;
          }
        }

        if (!runtime.metaReceived) {
          restoreOptimisticSnapshot(runtime);
          restoreComposerOnNoMeta?.();
        } else {
          settleAssistantMessage(runtime, {
            status: "failed",
            error: UNEXPECTED_STREAM_END_MESSAGE,
          });
          if (runtime.currentConversationId) {
            await conversation
              .reconcileConversation(runtime.currentConversationId, true)
              .catch(() => undefined);
          }
        }
        composer.setMotionSource("stream");
        composer.setComposerError({
          message: UNEXPECTED_STREAM_END_MESSAGE,
          retryable: false,
        });
        finalizeStreamState("error");
      } catch (error) {
        if (runtime.stopRequested) {
          if (!runtime.metaReceived) {
            restoreOptimisticSnapshot(runtime);
            restoreComposerOnNoMeta?.();
          } else if (runtime.currentConversationId) {
            settleAssistantMessage(runtime, {
              status: "cancelled",
              finishReason: "cancelled",
            });
            await conversation
              .reconcileConversation(runtime.currentConversationId, true)
              .catch(() => undefined);
          }
          finalizeStreamState("idle");
          return;
        }

        const message = describeError(error, "Service temporarily unavailable.");

        if (!runtime.metaReceived) {
          restoreOptimisticSnapshot(runtime);
          restoreComposerOnNoMeta?.();
        } else {
          settleAssistantMessage(runtime, {
            status: "failed",
            error: message,
          });
          if (runtime.currentConversationId) {
            await conversation
              .reconcileConversation(runtime.currentConversationId, true)
              .catch(() => undefined);
          }
        }

        composer.setMotionSource("stream");
        composer.setComposerError({
          message,
          retryable: false,
        });
        finalizeStreamState("error");
      } finally {
        composer.focusInput();
      }
    },
    [
      composer,
      conversation,
      finalizeStreamState,
      patchRuntimeMeta,
      restoreOptimisticSnapshot,
      settleAssistantMessage,
    ],
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
    if (provider === "dify" && snapshotUploads.length > 0) {
      composer.setMotionSource("user");
      composer.setComposerError({
        message: "Dify mode only supports text messages.",
        retryable: false,
      });
      return;
    }
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
        provider,
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
    provider,
  ]);

  const sendEditedMessage = useCallback(async (messageId: string) => {
    if (isBusy || composer.editingMessageId !== messageId) {
      return;
    }

    const conversationId = conversation.activeConversationIdRef.current;
    if (!conversationId) {
      return;
    }

    const detail = conversation.conversationDetailsRef.current[conversationId];
    if (!detail) {
      return;
    }

    const snapshotText = composer.input.trim();
    if (!snapshotText) {
      return;
    }

    const { userMessage, assistantMessage } = resolveLastTurn(detail.messages);
    if (
      !userMessage ||
      !assistantMessage ||
      userMessage.id !== messageId ||
      !isPureTextUserMessage(userMessage)
    ) {
      composer.setMotionSource("user");
      composer.setComposerError({
        message: "Only the latest plain-text user message can be edited.",
        retryable: false,
      });
      return;
    }

    composer.clearEditState();
    composer.setInput("");

    await runExistingTurnStream({
      conversationId,
      userMessage,
      assistantMessage,
      snapshotText,
      optimisticUpdater: (messages) =>
        messages.map((message) => {
          if (message.clientKey === userMessage.clientKey) {
            return rewriteUserMessageLocally(message, snapshotText);
          }

          if (message.clientKey === assistantMessage.clientKey) {
            return restartAssistantMessageLocally(message);
          }

          return message;
        }),
      streamFactory: (signal) =>
        editConversationMessageStream(
          conversationId,
          messageId,
          {
            input: {
              parts: [{ type: "text", text: snapshotText }],
            },
            generation: DEFAULT_GENERATION,
          },
          signal,
        ),
      restoreComposerOnNoMeta: () => composer.restoreEditState(messageId, snapshotText),
    });
  }, [composer, conversation, isBusy, runExistingTurnStream]);

  const regenerateMessage = useCallback(async (messageId: string) => {
    if (isBusy) {
      return;
    }

    const conversationId = conversation.activeConversationIdRef.current;
    if (!conversationId) {
      return;
    }

    const detail = conversation.conversationDetailsRef.current[conversationId];
    if (!detail) {
      return;
    }

    const { userMessage, assistantMessage } = resolveLastTurn(detail.messages);
    if (!userMessage || !assistantMessage || assistantMessage.id !== messageId) {
      composer.setMotionSource("user");
      composer.setComposerError({
        message: "Only the latest assistant response can be regenerated.",
        retryable: false,
      });
      return;
    }

    if (composer.isEditingMessage) {
      composer.cancelEdit();
    }

    await runExistingTurnStream({
      conversationId,
      userMessage,
      assistantMessage,
      snapshotText: "",
      optimisticUpdater: (messages) =>
        messages.map((message) =>
          message.clientKey === assistantMessage.clientKey
            ? restartAssistantMessageLocally(message)
            : message,
        ),
      streamFactory: (signal) =>
        regenerateConversationMessageStream(
          conversationId,
          messageId,
          {
            generation: DEFAULT_GENERATION,
          },
          signal,
        ),
    });
  }, [composer, conversation, isBusy, runExistingTurnStream]);

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
    sendEditedMessage,
    regenerateMessage,
    handleStop,
    handleRetry,
  };
};

export type ChatStreamController = ReturnType<typeof useChatStreamController>;
