import { describe, expect, it } from "vitest";
import { createStreamSession } from "./streamSession";
import { hasSendableContent, type PendingUpload } from "./model";

const createUpload = (overrides: Partial<PendingUpload>): PendingUpload => ({
  localId: overrides.localId ?? "upload-1",
  file: overrides.file ?? new File(["demo"], "diagram.png", { type: "image/png" }),
  previewUrl: overrides.previewUrl ?? "blob:demo",
  uploadId: overrides.uploadId ?? "upload_123",
  status: overrides.status ?? "ready",
  mediaType: overrides.mediaType ?? "image/png",
  byteSize: overrides.byteSize ?? 1024,
  error: overrides.error ?? null,
});

describe("streamSession", () => {
  it("detects when the composer has sendable text or ready uploads", () => {
    expect(hasSendableContent("", [])).toBe(false);
    expect(hasSendableContent("Hello", [])).toBe(true);
    expect(
      hasSendableContent("", [
        createUpload({
          status: "uploading",
          uploadId: null,
        }),
      ]),
    ).toBe(false);
    expect(hasSendableContent("", [createUpload({ uploadId: "upload_456" })])).toBe(true);
  });

  it("builds a stream session with optimistic messages and a payload", () => {
    const readyUpload = createUpload({
      localId: "upload-ready",
      uploadId: "upload_ready",
    });
    const erroredUpload = createUpload({
      localId: "upload-error",
      uploadId: null,
      status: "error",
      error: "Upload failed",
    });

    const session = createStreamSession({
      currentConversationId: null,
      snapshotText: "Please review this image",
      snapshotUploads: [readyUpload, erroredUpload],
      previousDraftMessages: [],
      previousConversation: null,
    });

    expect(session.readyUploads).toEqual([readyUpload]);
    expect(session.userMessage.role).toBe("user");
    expect(session.assistantMessage.role).toBe("assistant");
    expect(session.assistantMessage.isSkeleton).toBe(true);
    expect(session.payload.input.parts).toEqual([
      { type: "text", text: "Please review this image" },
      { type: "image", upload_id: "upload_ready" },
    ]);
    expect(session.runtime.snapshotUploads).toEqual([readyUpload, erroredUpload]);
  });
});
