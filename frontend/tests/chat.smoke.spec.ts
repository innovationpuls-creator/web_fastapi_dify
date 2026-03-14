import { expect, test, type Page } from "@playwright/test";

const healthPayload = {
  status: "ok",
  app_name: "dify-fastapi",
  version: "1.0.0",
  config_loaded: true,
  dify_enabled: false,
};

const timestamp = "2026-03-07T12:00:00.000Z";

type Summary = {
  id: string;
  title: string;
  updated_at: string;
  created_at: string;
  last_message_preview: string;
  message_count: number;
};

type Detail = Summary & {
  messages: Array<Record<string, unknown>>;
};

async function mockBootstrap(
  page: Page,
  options?: {
    health?: typeof healthPayload;
    conversations?: Summary[];
    details?: Record<string, Detail>;
  },
) {
  const health = options?.health ?? healthPayload;
  const conversations = options?.conversations ?? [];
  const details = options?.details ?? {};

  await page.route("http://127.0.0.1:8000/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(health),
    });
  });

  await page.route("http://127.0.0.1:8000/chat/conversations", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(conversations),
    });
  });

  await page.route(/http:\/\/127\.0\.0\.1:8000\/chat\/conversations\/[^/]+$/, async (route) => {
    const url = new URL(route.request().url());
    const conversationId = url.pathname.split("/").pop() ?? "";
    const detail = details[conversationId];

    if (detail) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(detail),
      });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "Not found.",
        request_id: "req_missing",
      }),
    });
  });

  await page.route(/http:\/\/127\.0\.0\.1:8000\/chat\/uploads\/.+/, async (route) => {
    await route.fulfill({
      status: 204,
      body: "",
    });
  });
}

const isoAtLocalNoon = (daysOffset = 0) => {
  const value = new Date();
  value.setHours(12, 0, 0, 0);
  value.setDate(value.getDate() + daysOffset);
  return value.toISOString();
};

test("mobile history sheet opens as a dialog and closes on Escape", async ({ page }) => {
  await mockBootstrap(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await page.getByRole("button", { name: "Open sidebar" }).click();
  await expect(page.getByRole("dialog", { name: "Conversation history" })).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
});

test("desktop collapse keeps the history button fixed while the page scrolls", async ({ page }) => {
  await mockBootstrap(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  await page.getByRole("button", { name: "Collapse sidebar" }).click();

  const restoreButton = page.getByRole("button", { name: "Expand sidebar" });
  await expect(restoreButton).toBeVisible();
  await expect(restoreButton).toContainText("History");
  const initialBox = await restoreButton.boundingBox();

  await page.evaluate(() => {
    const filler = document.createElement("div");
    filler.setAttribute("data-testid", "page-scroll-filler");
    filler.style.height = "3200px";
    document.body.appendChild(filler);
    window.scrollTo(0, 2200);
  });
  await page.waitForFunction(() => window.scrollY > 1000);

  const scrolledBox = await restoreButton.boundingBox();
  await expect(restoreButton).toBeVisible();
  expect(Math.abs(Math.round((scrolledBox?.x ?? 0) - (initialBox?.x ?? 0)))).toBeLessThanOrEqual(1);
  expect(Math.abs(Math.round((scrolledBox?.y ?? 0) - (initialBox?.y ?? 0)))).toBeLessThanOrEqual(1);

  await restoreButton.click();
  await expect(page.getByRole("button", { name: "Collapse sidebar" })).toBeVisible();
});

test("send then stop restores the draft input", async ({ page }) => {
  await mockBootstrap(page);
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);

    window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();

      if (!url.endsWith("/chat/stream")) {
        return originalFetch(input, init);
      }

      const signal = init?.signal;
      const stream = new ReadableStream({
        start(controller) {
          signal?.addEventListener(
            "abort",
            () => {
              controller.error(new DOMException("Aborted", "AbortError"));
            },
            { once: true },
          );
        },
      });

      return new Response(stream, {
        status: 200,
        headers: {
          "Content-Type": "application/x-ndjson",
        },
      });
    }) as typeof window.fetch;
  });

  await page.goto("/");

  const textbox = page.getByRole("textbox", { name: "Message AI" });
  await textbox.fill("Hello smoke");
  await page.getByRole("button", { name: "Send" }).click();

  const stopButton = page.getByRole("button", { name: "Stop" });
  await expect(stopButton).toBeVisible();

  await stopButton.click();

  await expect(textbox).toHaveValue("Hello smoke");
  await expect(stopButton).toBeHidden();
});

test("failed uploads can be retried into a ready state", async ({ page }) => {
  await mockBootstrap(page);

  let uploadAttempts = 0;
  await page.route("http://127.0.0.1:8000/chat/uploads", async (route) => {
    uploadAttempts += 1;

    if (uploadAttempts === 1) {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Image upload failed.",
          request_id: "req_upload_error",
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        upload_id: "upload_retry",
        url: "/chat/assets/upload_retry",
        media_type: "image/png",
        byte_size: 1024,
        created_at: timestamp,
      }),
    });
  });

  await page.goto("/");

  await page.locator('input[type="file"]').setInputFiles({
    name: "diagram.png",
    mimeType: "image/png",
    buffer: Buffer.from("fake image"),
  });

  const uploadCard = page.locator(".pending-upload").filter({ hasText: "diagram.png" });
  await expect(uploadCard).toContainText("Image upload failed.");

  await uploadCard.getByRole("button", { name: "Retry" }).click();

  await expect(uploadCard).toContainText("1 KB");
  await expect(uploadCard.getByRole("button", { name: "Retry" })).toHaveCount(0);
});

test("sidebar groups conversations and renames from the overflow menu", async ({ page }) => {
  const today = isoAtLocalNoon(0);
  const yesterday = isoAtLocalNoon(-1);
  const todayConversation: Summary = {
    id: "conversation-today",
    title: "Hello",
    updated_at: today,
    created_at: today,
    last_message_preview: "Hello",
    message_count: 2,
  };
  const yesterdayConversation: Summary = {
    id: "conversation-yesterday",
    title: "Kant Notes",
    updated_at: yesterday,
    created_at: yesterday,
    last_message_preview: "Kant Notes",
    message_count: 2,
  };

  await mockBootstrap(page, {
    conversations: [todayConversation, yesterdayConversation],
    details: {
      "conversation-today": {
        ...todayConversation,
        messages: [],
      },
    },
  });

  await page.route("http://127.0.0.1:8000/chat/conversations/conversation-yesterday", async (route) => {
    if (route.request().method() === "PATCH") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...yesterdayConversation,
          title: "Ethics Notes",
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...yesterdayConversation,
        messages: [],
      }),
    });
  });

  await page.goto("/");

  await expect(page.getByText("Today")).toBeVisible();
  await expect(page.getByText("Yesterday")).toBeVisible();

  await page.getByRole("button", { name: "Open actions for Kant Notes" }).click();
  await page.getByRole("menuitem", { name: "Rename" }).click();

  const textbox = page.getByRole("textbox", { name: "Rename conversation" });
  await textbox.fill("Ethics Notes");
  await textbox.press("Enter");

  await expect(page.getByRole("button", { name: "Ethics Notes", exact: true })).toBeVisible();
});

test("latest turn supports edit and regenerate flows", async ({ page }) => {
  const conversation: Summary = {
    id: "conversation-edit",
    title: "Reading First",
    updated_at: timestamp,
    created_at: timestamp,
    last_message_preview: "Please improve the layout",
    message_count: 2,
  };

  await mockBootstrap(page, {
    conversations: [conversation],
    details: {
      "conversation-edit": {
        ...conversation,
        messages: [
          {
            id: "message-user",
            conversation_id: conversation.id,
            role: "user",
            status: "completed",
            parts: [{ type: "text", text: "Please improve the layout" }],
            created_at: timestamp,
            updated_at: timestamp,
            thinking_completed_at: null,
            model: null,
            finish_reason: null,
            error: null,
            metrics: null,
          },
          {
            id: "message-assistant",
            conversation_id: conversation.id,
            role: "assistant",
            status: "completed",
            parts: [{ type: "text", text: "## Key updates\n\nStart with stronger contrast." }],
            created_at: timestamp,
            updated_at: timestamp,
            thinking_completed_at: timestamp,
            model: "gpt-test",
            finish_reason: "stop",
            error: null,
            metrics: {
              input_tokens: 120,
              output_tokens: 222,
              total_tokens: 342,
              latency_ms: 1200,
            },
          },
        ],
      },
    },
  });

  await page.route(
    "http://127.0.0.1:8000/chat/conversations/conversation-edit/messages/message-user/edit-stream",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/x-ndjson",
        body: [
          JSON.stringify({
            event: "meta",
            model: "gpt-test",
            conversation_id: conversation.id,
            user_message_id: "message-user",
            assistant_message_id: "message-assistant",
            title: conversation.title,
          }),
          JSON.stringify({
            event: "delta",
            model: "gpt-test",
            delta: "## Key updates\n\nThe layout now follows a reading-first structure.",
          }),
          JSON.stringify({
            event: "done",
            model: "gpt-test",
            message: {
              id: "message-assistant",
              conversation_id: conversation.id,
              role: "assistant",
              status: "completed",
              parts: [
                { type: "text", text: "## Key updates\n\nThe layout now follows a reading-first structure." },
              ],
              created_at: timestamp,
              updated_at: timestamp,
              thinking_completed_at: timestamp,
              model: "gpt-test",
              finish_reason: "stop",
              error: null,
              metrics: {
                input_tokens: 130,
                output_tokens: 210,
                total_tokens: 340,
                latency_ms: 980,
              },
            },
            conversation: {
              ...conversation,
              last_message_preview: "Please make the bubbles reading first",
            },
          }),
        ].join("\n"),
      });
    },
  );

  await page.route(
    "http://127.0.0.1:8000/chat/conversations/conversation-edit/messages/message-assistant/regenerate-stream",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/x-ndjson",
        body: [
          JSON.stringify({
            event: "meta",
            model: "gpt-test",
            conversation_id: conversation.id,
            user_message_id: "message-user",
            assistant_message_id: "message-assistant",
            title: conversation.title,
          }),
          JSON.stringify({
            event: "done",
            model: "gpt-test",
            message: {
              id: "message-assistant",
              conversation_id: conversation.id,
              role: "assistant",
              status: "completed",
              parts: [{ type: "text", text: "## Key updates\n\nHere is a regenerated version." }],
              created_at: timestamp,
              updated_at: timestamp,
              thinking_completed_at: timestamp,
              model: "gpt-test",
              finish_reason: "stop",
              error: null,
              metrics: {
                input_tokens: 125,
                output_tokens: 205,
                total_tokens: 330,
                latency_ms: 1100,
              },
            },
            conversation,
          }),
        ].join("\n"),
      });
    },
  );

  await page.goto("/");

  await expect(page.getByText("Tokens: 342")).toBeVisible();
  await expect(page.getByRole("button", { name: "Edit message" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Regenerate response" })).toBeVisible();

  await page.getByRole("button", { name: "Edit message" }).click();
  const textbox = page.getByRole("textbox", { name: "Message AI" });
  await expect(textbox).toHaveValue("Please improve the layout");
  await textbox.fill("Please make the bubbles reading first");
  await page.getByRole("button", { name: "Update" }).click();

  await expect(page.getByText("The layout now follows a reading-first structure.")).toBeVisible();
  await expect(page.getByText("Tokens: 340")).toBeVisible();

  await page.getByRole("button", { name: "Regenerate response" }).click();
  await expect(page.getByText("Here is a regenerated version.")).toBeVisible();
  await expect(page.getByText("Latency: 1.1s")).toBeVisible();
});

test("dify toggle is visible but disabled when the backend is not configured", async ({ page }) => {
  await mockBootstrap(page, {
    health: { ...healthPayload, dify_enabled: false },
  });
  await page.goto("/");

  const toggle = page.getByRole("checkbox", { name: "Toggle Dify mode" });
  await expect(toggle).toBeVisible();
  await expect(toggle).toBeDisabled();
  await expect(page.getByText("未配置")).toBeVisible();
});

test("dify toggle restores the saved mode when available", async ({ page }) => {
  await mockBootstrap(page, {
    health: { ...healthPayload, dify_enabled: true },
  });
  await page.addInitScript(() => {
    window.localStorage.setItem("chat-provider-mode", "dify");
  });
  await page.goto("/");

  await expect(page.getByRole("checkbox", { name: "Toggle Dify mode" })).toBeChecked();
  await expect(page.getByText("Text only")).toBeVisible();
});
