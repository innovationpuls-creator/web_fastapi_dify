import { expect, test, type Page } from "@playwright/test";

const healthPayload = {
  status: "ok",
  app_name: "dify-fastapi",
  version: "1.0.0",
  config_loaded: true,
};

const timestamp = "2026-03-07T12:00:00.000Z";

async function mockBootstrap(page: Page) {
  await page.route("http://127.0.0.1:8000/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(healthPayload),
    });
  });

  await page.route("http://127.0.0.1:8000/conversations", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.route(/http:\/\/127\.0\.0\.1:8000\/conversations\/.+/, async (route) => {
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

test("mobile history sheet opens as a dialog and closes on Escape", async ({ page }) => {
  await mockBootstrap(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await page.getByRole("button", { name: "Open sidebar" }).click();
  await expect(
    page.getByRole("dialog", { name: "Conversation history" }),
  ).toBeVisible();

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
  const restoreButtonBox = await restoreButton.boundingBox();

  await page.evaluate(() => {
    const filler = document.createElement("div");
    filler.setAttribute("data-testid", "page-scroll-filler");
    filler.style.height = "3200px";
    document.body.appendChild(filler);
    window.scrollTo(0, 2200);
  });
  await page.waitForFunction(() => window.scrollY > 1000);

  const scrolledRestoreButtonBox = await restoreButton.boundingBox();
  await expect(restoreButton).toBeVisible();
  expect(
    Math.abs(Math.round(scrolledRestoreButtonBox?.x ?? -1) - Math.round(restoreButtonBox?.x ?? -1)),
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs(Math.round(scrolledRestoreButtonBox?.y ?? -1) - Math.round(restoreButtonBox?.y ?? -1)),
  ).toBeLessThanOrEqual(1);

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
