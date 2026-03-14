import type { ConversationSummary } from "../../services/api";

export type ConversationHistoryGroup = {
  label: "Today" | "Yesterday" | "Earlier";
  items: ConversationSummary[];
};

const startOfLocalDay = (value: Date) =>
  new Date(value.getFullYear(), value.getMonth(), value.getDate());

export const normalizeConversationTitle = (title: string) =>
  title.replace(/\s+/g, " ").trim();

export const groupConversationsByUpdatedAt = (
  conversations: ConversationSummary[],
  now = new Date(),
): ConversationHistoryGroup[] => {
  const todayStart = startOfLocalDay(now).getTime();
  const yesterdayStart = todayStart - 24 * 60 * 60 * 1000;

  const buckets: ConversationHistoryGroup[] = [
    { label: "Today", items: [] },
    { label: "Yesterday", items: [] },
    { label: "Earlier", items: [] },
  ];

  conversations.forEach((conversation) => {
    const updatedAt = new Date(conversation.updated_at).getTime();
    if (!Number.isFinite(updatedAt)) {
      buckets[2].items.push(conversation);
      return;
    }

    if (updatedAt >= todayStart) {
      buckets[0].items.push(conversation);
      return;
    }

    if (updatedAt >= yesterdayStart) {
      buckets[1].items.push(conversation);
      return;
    }

    buckets[2].items.push(conversation);
  });

  return buckets.filter((bucket) => bucket.items.length > 0);
};
