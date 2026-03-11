import { describe, expect, it } from "vitest";

import { formatThoughtSummary } from "./ConversationMessage";

describe("formatThoughtSummary", () => {
  it("uses thinking completion time instead of final answer time", () => {
    expect(
      formatThoughtSummary(
        "2026-03-07T12:00:00.000Z",
        "2026-03-07T12:00:10.000Z",
        "2026-03-07T12:00:03.000Z",
        false,
      ),
    ).toBe("Thought for 3 seconds");
  });
});
