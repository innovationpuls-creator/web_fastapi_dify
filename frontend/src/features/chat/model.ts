import {
  ApiError,
  resolveAssetUrl,
  type ChatMessageResponse,
  type ConversationDetail,
  type ConversationSummary,
  type GenerationOptions,
  type TextMessagePart,
} from "../../services/api";
import { hasCompleteThinkingBlock } from "../../utils/assistantContent";

export const EMPTY_TITLE = "New chat";
export const SIDEBAR_WIDTH = 220;
export const MAX_UPLOAD_COUNT = 4;
export const MAX_UPLOAD_BYTES = 5_000_000;
export const ALLOWED_UPLOAD_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
export const DEFAULT_GENERATION: GenerationOptions = {
  temperature: 0.7,
  max_output_tokens: 2048,
};
export const UNEXPECTED_STREAM_END_MESSAGE = "Chat stream ended unexpectedly.";

export type AppPhase = "idle" | "streaming" | "stopping" | "error";

export type DisplayImagePart = {
  type: "image";
  media_type: string;
  url: string;
  asset_id?: string;
  upload_id?: string;
};

export type DisplayPart = TextMessagePart | DisplayImagePart;

export type DisplayMessage = Omit<ChatMessageResponse, "parts"> & {
  clientKey: string;
  parts: DisplayPart[];
  isSkeleton?: boolean;
};

export type DisplayConversation = Omit<ConversationDetail, "messages"> & {
  messages: DisplayMessage[];
};

export type PendingUpload = {
  localId: string;
  file: File;
  previewUrl: string;
  uploadId: string | null;
  status: "uploading" | "ready" | "error";
  mediaType: string;
  byteSize: number;
  error?: string | null;
};

export type ComposerError = {
  message: string;
  retryable: boolean;
};

export type ScreenError = {
  message: string;
};

export type StreamRuntime = {
  controller: AbortController;
  originConversationId: string | null;
  currentConversationId: string | null;
  userClientKey: string;
  assistantClientKey: string;
  userMessageId: string;
  assistantMessageId: string;
  snapshotText: string;
  snapshotUploads: PendingUpload[];
  previousDraftMessages: DisplayMessage[];
  previousConversation: DisplayConversation | null;
  metaReceived: boolean;
  stopRequested: boolean;
};

export const createLocalId = (prefix: string) => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

export const nowIso = () => new Date().toISOString();

export const isReadyUpload = (
  upload: PendingUpload,
): upload is PendingUpload & { uploadId: string } =>
  upload.status === "ready" && typeof upload.uploadId === "string" && upload.uploadId.length > 0;

export const hasSendableContent = (input: string, uploads: PendingUpload[]) =>
  input.trim().length > 0 || uploads.some(isReadyUpload);

export const cloneMessage = (message: DisplayMessage): DisplayMessage => ({
  ...message,
  parts: message.parts.map((part) => ({ ...part })),
});

export const cloneConversation = (conversation: DisplayConversation | null) =>
  conversation
    ? {
        ...conversation,
        messages: conversation.messages.map(cloneMessage),
      }
    : null;

export const cloneUpload = (upload: PendingUpload): PendingUpload => ({ ...upload });

export const resizeTextarea = (element: HTMLTextAreaElement | null) => {
  if (!element) {
    return;
  }

  element.style.height = "0px";
  element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
};

export const moveSummaryToTop = (
  items: ConversationSummary[],
  summary: ConversationSummary,
): ConversationSummary[] => [summary, ...items.filter((item) => item.id !== summary.id)];

export const replaceSummary = (items: ConversationSummary[], summary: ConversationSummary) => {
  if (!items.some((item) => item.id === summary.id)) {
    return items;
  }

  return items.map((item) => (item.id === summary.id ? summary : item));
};

export const summaryFromDetail = (detail: DisplayConversation): ConversationSummary => ({
  id: detail.id,
  title: detail.title,
  updated_at: detail.updated_at,
  created_at: detail.created_at,
  last_message_preview: detail.last_message_preview,
  message_count: detail.message_count,
});

export const deriveTitle = (text: string, imageCount: number) => {
  const firstLine = text
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean);

  if (firstLine) {
    return firstLine.length > 40 ? firstLine.slice(0, 40).trimEnd() : firstLine;
  }

  return imageCount === 0 ? EMPTY_TITLE : `Images ${nowIso().slice(0, 16).replace("T", " ")}`;
};

export const previewFromDraft = (text: string, imageCount: number) => {
  const collapsed = text.trim().replace(/\s+/g, " ");
  if (collapsed) {
    return collapsed.length > 120 ? `${collapsed.slice(0, 117)}...` : collapsed;
  }

  if (imageCount <= 1) {
    return "[Image]";
  }

  return `[${imageCount} images]`;
};

export const getMessageText = (message: DisplayMessage) =>
  message.parts
    .filter((part): part is TextMessagePart => part.type === "text")
    .map((part) => part.text)
    .join("\n\n");

export const buildAssistantParts = (message: DisplayMessage, text: string): DisplayPart[] => {
  const nextParts: DisplayPart[] = message.parts
    .filter((part): part is DisplayImagePart => part.type === "image")
    .map((part) => ({ ...part }));
  if (text) {
    nextParts.push({ type: "text", text });
  }
  return nextParts;
};

export const resolveThinkingCompletedAt = (
  thinkingCompletedAt: string | null | undefined,
  text: string,
  updatedAt: string,
) => {
  if (thinkingCompletedAt) {
    return thinkingCompletedAt;
  }

  return hasCompleteThinkingBlock(text) ? updatedAt : null;
};

export const withAssistantText = (message: DisplayMessage, text: string, model?: string) => {
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
};

export const isRetryableError = (error: unknown) =>
  error instanceof ApiError ? error.retryable : true;

export const describeError = (error: unknown, fallback: string) => {
  if (error instanceof ApiError) {
    return error.detail;
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return fallback;
};

export const toDisplayMessage = (message: ChatMessageResponse): DisplayMessage => ({
  ...message,
  thinking_completed_at: message.thinking_completed_at ?? null,
  clientKey: message.id,
  parts: message.parts.map((part) =>
    part.type === "image"
      ? {
          ...part,
          url: resolveAssetUrl(part.url),
        }
      : { ...part },
  ),
});

export const toDisplayConversation = (conversation: ConversationDetail): DisplayConversation => ({
  ...conversation,
  messages: conversation.messages.map(toDisplayMessage),
});

export const isBusyPhase = (phase: AppPhase) => phase === "streaming" || phase === "stopping";
