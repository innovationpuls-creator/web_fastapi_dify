import {
  buildAssistantParts,
  getMessageText,
  nowIso,
  previewFromDraft,
  resolveThinkingCompletedAt,
  type DisplayConversation,
  type DisplayMessage,
  type StreamRuntime,
} from "./model";

export type StreamMetaPayload = {
  conversationId: string;
  title: string;
  model: string;
  userMessageId: string;
  assistantMessageId: string;
};

export type AssistantSettleUpdates = {
  status: DisplayMessage["status"];
  error?: string | null;
  finishReason?: string | null;
  model?: string | null;
  thinkingCompletedAt?: string | null;
};

const updateMessageByClientKey = (
  messages: DisplayMessage[],
  clientKey: string,
  updater: (message: DisplayMessage) => DisplayMessage,
) => {
  const lastIndex = messages.length - 1;
  if (lastIndex >= 0 && messages[lastIndex].clientKey === clientKey) {
    const nextMessage = updater(messages[lastIndex]);
    if (nextMessage === messages[lastIndex]) {
      return messages;
    }

    const nextMessages = messages.slice();
    nextMessages[lastIndex] = nextMessage;
    return nextMessages;
  }

  const index = messages.findIndex((message) => message.clientKey === clientKey);
  if (index < 0) {
    return messages;
  }

  const nextMessage = updater(messages[index]);
  if (nextMessage === messages[index]) {
    return messages;
  }

  const nextMessages = messages.slice();
  nextMessages[index] = nextMessage;
  return nextMessages;
};

export const appendOptimisticMessages = (
  messages: DisplayMessage[],
  userMessage: DisplayMessage,
  assistantMessage: DisplayMessage,
) => [...messages, userMessage, assistantMessage];

export const settleAssistantMessages = (
  messages: DisplayMessage[],
  assistantClientKey: string,
  updates: AssistantSettleUpdates,
) =>
  updateMessageByClientKey(messages, assistantClientKey, (message) => {
    const text = getMessageText(message);
    const updatedAt = nowIso();
    return {
      ...message,
      status: updates.status,
      error: updates.error ?? null,
      finish_reason: updates.finishReason ?? message.finish_reason ?? null,
      model: updates.model ?? message.model ?? null,
      updated_at: updatedAt,
      thinking_completed_at:
        updates.thinkingCompletedAt ??
        resolveThinkingCompletedAt(message.thinking_completed_at, text, updatedAt),
      parts: buildAssistantParts(message, text),
      isSkeleton: false,
    };
  });

export const applyAssistantDelta = (
  messages: DisplayMessage[],
  assistantClientKey: string,
  delta: string,
  model?: string,
) =>
  updateMessageByClientKey(messages, assistantClientKey, (message) => {
    const text = `${getMessageText(message)}${delta}`;
    const updatedAt = nowIso();
    return {
      ...message,
      parts: buildAssistantParts(message, text),
      status: "streaming" as const,
      model: model ?? message.model ?? null,
      updated_at: updatedAt,
      thinking_completed_at: resolveThinkingCompletedAt(
        message.thinking_completed_at,
        text,
        updatedAt,
      ),
      isSkeleton: false,
    };
  });

export const replaceAssistantMessage = (
  messages: DisplayMessage[],
  assistantClientKey: string,
  nextAssistant: DisplayMessage,
) =>
  updateMessageByClientKey(messages, assistantClientKey, () => nextAssistant);

export const applyStreamMetaToMessages = (
  messages: DisplayMessage[],
  runtime: StreamRuntime,
  meta: StreamMetaPayload,
) =>
  updateMessageByClientKey(
    updateMessageByClientKey(messages, runtime.userClientKey, (message) => ({
      ...message,
      id: meta.userMessageId,
      conversation_id: meta.conversationId,
    })),
    runtime.assistantClientKey,
    (message) => ({
      ...message,
      id: meta.assistantMessageId,
      conversation_id: meta.conversationId,
      model: meta.model,
    }),
  );

export const buildPromotedDraftConversation = (
  draftMessages: DisplayMessage[],
  runtime: StreamRuntime,
  meta: StreamMetaPayload,
): DisplayConversation => {
  const promotedMessages = applyStreamMetaToMessages(draftMessages, runtime, meta);
  const preview = previewFromDraft(
    runtime.snapshotText,
    runtime.snapshotUploads.length,
  );
  const createdAt = promotedMessages[0]?.created_at ?? nowIso();

  return {
    id: meta.conversationId,
    title: meta.title,
    created_at: createdAt,
    updated_at: createdAt,
    last_message_preview: preview,
    message_count: promotedMessages.length,
    messages: promotedMessages,
  };
};
