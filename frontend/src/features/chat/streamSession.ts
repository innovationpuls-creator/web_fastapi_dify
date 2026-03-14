import type { ChatProvider, ChatStreamRequest } from "../../services/api";
import {
  DEFAULT_GENERATION,
  createLocalId,
  isReadyUpload,
  nowIso,
  type DisplayConversation,
  type DisplayImagePart,
  type DisplayMessage,
  type PendingUpload,
  type StreamRuntime,
} from "./model";

type CreateStreamSessionOptions = {
  currentConversationId: string | null;
  provider: ChatProvider;
  snapshotText: string;
  snapshotUploads: PendingUpload[];
  previousDraftMessages: DisplayMessage[];
  previousConversation: DisplayConversation | null;
};

export type StreamSession = {
  readyUploads: Array<PendingUpload & { uploadId: string }>;
  userMessage: DisplayMessage;
  assistantMessage: DisplayMessage;
  runtime: StreamRuntime;
  payload: ChatStreamRequest;
};

export const createStreamSession = ({
  currentConversationId,
  provider,
  snapshotText,
  snapshotUploads,
  previousDraftMessages,
  previousConversation,
}: CreateStreamSessionOptions): StreamSession => {
  const readyUploads = provider === "dify" ? [] : snapshotUploads.filter(isReadyUpload);
  const createdAt = nowIso();
  const userClientKey = createLocalId("user");
  const assistantClientKey = createLocalId("assistant");

  const userMessage: DisplayMessage = {
    clientKey: userClientKey,
    id: userClientKey,
    conversation_id: currentConversationId ?? "",
    role: "user",
    status: "completed",
    parts: [
      ...(snapshotText ? [{ type: "text", text: snapshotText } as const] : []),
      ...readyUploads.map<DisplayImagePart>((upload) => ({
        type: "image",
        media_type: upload.mediaType,
        url: upload.previewUrl,
        upload_id: upload.uploadId,
      })),
    ],
    created_at: createdAt,
    updated_at: createdAt,
    thinking_completed_at: null,
    model: null,
    finish_reason: null,
    error: null,
  };

  const assistantMessage: DisplayMessage = {
    clientKey: assistantClientKey,
    id: assistantClientKey,
    conversation_id: currentConversationId ?? "",
    role: "assistant",
    status: "streaming",
    parts: [],
    created_at: createdAt,
    updated_at: createdAt,
    thinking_completed_at: null,
    model: null,
    finish_reason: null,
    error: null,
    isSkeleton: true,
  };

  const runtime: StreamRuntime = {
    controller: new AbortController(),
    originConversationId: currentConversationId,
    currentConversationId,
    userClientKey,
    assistantClientKey,
    userMessageId: userClientKey,
    assistantMessageId: assistantClientKey,
    snapshotText,
    snapshotUploads,
    previousDraftMessages,
    previousConversation,
    metaReceived: false,
    stopRequested: false,
  };

  const payload: ChatStreamRequest = {
    ...(currentConversationId ? { conversation_id: currentConversationId } : {}),
    provider,
    input: {
      parts: [
        ...(snapshotText ? [{ type: "text", text: snapshotText } as const] : []),
        ...readyUploads.map((upload) => ({
          type: "image" as const,
          upload_id: upload.uploadId,
        })),
      ],
    },
    generation: DEFAULT_GENERATION,
  };

  return {
    readyUploads,
    userMessage,
    assistantMessage,
    runtime,
    payload,
  };
};
