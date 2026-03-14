import type { MessageMetrics } from "../../services/api";
import { getMessageText, messageHasImages, type DisplayMessage } from "./model";

export type LastTurnActions = {
  editableUserMessageId: string | null;
  regenerableAssistantMessageId: string | null;
  assistantMetrics: MessageMetrics | null;
};

export const isPureTextUserMessage = (message: DisplayMessage) =>
  message.role === "user" &&
  !messageHasImages(message) &&
  getMessageText(message).trim().length > 0;

export const resolveLastTurn = (messages: DisplayMessage[]) => {
  const assistantIndex = [...messages].reverse().findIndex((message) => message.role === "assistant");
  if (assistantIndex < 0) {
    return {
      userMessage: null,
      assistantMessage: null,
    };
  }

  const resolvedAssistantIndex = messages.length - 1 - assistantIndex;
  const userIndex = messages
    .slice(0, resolvedAssistantIndex)
    .map((message) => message.role)
    .lastIndexOf("user");

  if (userIndex < 0) {
    return {
      userMessage: null,
      assistantMessage: null,
    };
  }

  return {
    userMessage: messages[userIndex],
    assistantMessage: messages[resolvedAssistantIndex],
  };
};

export const resolveLastTurnActions = (
  messages: DisplayMessage[],
  isStreaming: boolean,
): LastTurnActions => {
  if (isStreaming) {
    return {
      editableUserMessageId: null,
      regenerableAssistantMessageId: null,
      assistantMetrics: null,
    };
  }

  const { userMessage, assistantMessage } = resolveLastTurn(messages);
  if (!userMessage || !assistantMessage) {
    return {
      editableUserMessageId: null,
      regenerableAssistantMessageId: null,
      assistantMetrics: null,
    };
  }

  return {
    editableUserMessageId: isPureTextUserMessage(userMessage) ? userMessage.id : null,
    regenerableAssistantMessageId: assistantMessage.id,
    assistantMetrics: assistantMessage.metrics ?? null,
  };
};
