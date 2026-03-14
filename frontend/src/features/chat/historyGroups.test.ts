import { describe, expect, it } from "vitest";
import type { ConversationSummary } from "../../services/api";
import { groupConversationsByUpdatedAt, normalizeConversationTitle } from "./historyGroups";

const createConversation = (
  id: string,
  updatedAt: string,
  title = id,
): ConversationSummary => ({
  id,
  title,
  updated_at: updatedAt,
  created_at: updatedAt,
  last_message_preview: title,
  message_count: 1,
});

describe("historyGroups", () => {
  it("groups conversations into Today, Yesterday, and Earlier using local calendar days", () => {
    const groups = groupConversationsByUpdatedAt(
      [
        createConversation("today-1", "2026-03-14T09:12:00.000+08:00"),
        createConversation("today-2", "2026-03-14T02:20:00.000+08:00"),
        createConversation("yesterday", "2026-03-13T23:50:00.000+08:00"),
        createConversation("earlier", "2026-03-10T18:00:00.000+08:00"),
      ],
      new Date("2026-03-14T12:00:00.000+08:00"),
    );

    expect(groups).toEqual([
      {
        label: "Today",
        items: [expect.objectContaining({ id: "today-1" }), expect.objectContaining({ id: "today-2" })],
      },
      {
        label: "Yesterday",
        items: [expect.objectContaining({ id: "yesterday" })],
      },
      {
        label: "Earlier",
        items: [expect.objectContaining({ id: "earlier" })],
      },
    ]);
  });

  it("collapses whitespace and trims conversation titles before submit", () => {
    expect(normalizeConversationTitle("   Kant   and \n practical   reason   ")).toBe(
      "Kant and practical reason",
    );
  });
});
