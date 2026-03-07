import type { ConversationSummary } from "../../services/api";
import {
  moveSummaryToTop,
  replaceSummary,
  type DisplayConversation,
  type DisplayMessage,
} from "./model";

export const syncSummaryInList = (
  items: ConversationSummary[],
  summary: ConversationSummary,
  moveToTop = false,
) => (moveToTop ? moveSummaryToTop(items, summary) : replaceSummary(items, summary));

export const patchConversationDetailMessages = (
  detail: DisplayConversation | undefined,
  updater: (messages: DisplayMessage[]) => DisplayMessage[],
) =>
  detail
    ? {
        ...detail,
        messages: updater(detail.messages),
      }
    : detail;

export const removeConversationDetail = (
  details: Record<string, DisplayConversation>,
  conversationId: string,
) => {
  const next = { ...details };
  delete next[conversationId];
  return next;
};

export const removeConversationSummary = (
  items: ConversationSummary[],
  conversationId: string,
) => items.filter((item) => item.id !== conversationId);

export const resolvePreferredConversationId = (
  items: ConversationSummary[],
  preferredId?: string | null,
) =>
  preferredId && items.some((item) => item.id === preferredId)
    ? preferredId
    : items[0]?.id ?? null;

export const resolveNextConversationId = (
  items: ConversationSummary[],
  removedConversationId: string,
) => items.find((item) => item.id !== removedConversationId)?.id ?? null;
