export type ApiErrorResponse = {
  detail: string;
  request_id: string;
  upstream_error?: string | null;
};

export type HealthResponse = {
  status: string;
  app_name: string;
  version: string;
  config_loaded: boolean;
  dify_enabled: boolean;
};

export type DeepHealthResponse = {
  status: string;
  upstream_status: string;
  model: string | null;
  latency_ms: number | null;
  error: string | null;
};

export type GenerationOptions = {
  temperature: number;
  max_output_tokens: number | null;
};

export type ChatProvider = "openai" | "dify";

export type TextInputPart = {
  type: "text";
  text: string;
};

export type ImageInputPart = {
  type: "image";
  upload_id: string;
};

export type ChatInputPart = TextInputPart | ImageInputPart;

export type ChatStreamRequest = {
  conversation_id?: string | null;
  provider: ChatProvider;
  input: {
    parts: ChatInputPart[];
  };
  generation: GenerationOptions;
};

export type EditMessageStreamRequest = {
  input: {
    parts: TextInputPart[];
  };
  generation: GenerationOptions;
};

export type RegenerateMessageStreamRequest = {
  generation: GenerationOptions;
};

export type TextMessagePart = {
  type: "text";
  text: string;
};

export type ImageMessagePart = {
  type: "image";
  asset_id: string;
  media_type: string;
  url: string;
};

export type MessagePart = TextMessagePart | ImageMessagePart;

export type MessageMetrics = {
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  latency_ms: number | null;
};

export type ChatMessageResponse = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  status: "completed" | "streaming" | "failed" | "cancelled";
  parts: MessagePart[];
  created_at: string;
  updated_at: string;
  thinking_completed_at?: string | null;
  model?: string | null;
  finish_reason?: string | null;
  error?: string | null;
  metrics?: MessageMetrics | null;
};

export type ConversationSummary = {
  id: string;
  title: string;
  updated_at: string;
  created_at: string;
  last_message_preview: string;
  message_count: number;
};

export type ConversationDetail = ConversationSummary & {
  messages: ChatMessageResponse[];
};

export type CancelMessageResponse = {
  message: ChatMessageResponse;
  conversation: ConversationSummary;
};

export type ConversationRenameRequest = {
  title: string;
};

export type ChatStreamEvent = {
  event: "meta" | "delta" | "done" | "error";
  model: string;
  conversation_id?: string | null;
  user_message_id?: string | null;
  assistant_message_id?: string | null;
  title?: string | null;
  delta?: string;
  message?: ChatMessageResponse | null;
  conversation?: ConversationSummary | null;
  finish_reason?: string | null;
  error?: string | null;
};

export type ChatUploadResponse = {
  upload_id: string;
  url: string;
  media_type: string;
  byte_size: number;
  created_at: string;
};

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const NETWORK_UNAVAILABLE_MESSAGE = "Service temporarily unavailable.";
const EMPTY_STREAM_BODY_MESSAGE = "Chat stream response was empty.";
const DEFAULT_JSON_REQUEST_TIMEOUT_MS = 8_000;
const FILE_UPLOAD_TIMEOUT_MS = 30_000;
const STREAM_CONNECT_TIMEOUT_MS = 10_000;

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
  /\/+$/,
  "",
);
const assetBaseUrl = (import.meta.env.VITE_ASSET_BASE_URL || "").replace(/\/+$/, "");

const isJsonResponse = (contentType: string | null) =>
  typeof contentType === "string" && contentType.includes("application/json");

const buildApiUrl = (path: string) => {
  const normalizedPath = path.replace(/^\/+/, "");
  return new URL(normalizedPath, `${apiBaseUrl}/`).toString();
};

export function resolveAssetUrl(path: string) {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }

  const normalizedPath = path.replace(/^\/+/, "");
  const base = assetBaseUrl || new URL(`${apiBaseUrl}/`).origin;
  return new URL(normalizedPath, `${base}/`).toString();
}

export class ApiError extends Error {
  status: number;
  detail: string;
  requestId: string;
  upstreamError: string | null;
  retryable: boolean;

  constructor({
    status,
    detail,
    requestId,
    upstreamError,
  }: {
    status: number;
    detail: string;
    requestId: string;
    upstreamError?: string | null;
  }) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.requestId = requestId;
    this.upstreamError = upstreamError ?? null;
    this.retryable = status === 0 || status >= 500;
  }
}

export const isAbortError = (error: unknown) =>
  error instanceof DOMException && error.name === "AbortError";

const buildUnavailableApiError = () =>
  new ApiError({
    status: 0,
    detail: NETWORK_UNAVAILABLE_MESSAGE,
    requestId: "-",
  });

const createTimedSignal = (sourceSignal?: AbortSignal | null, timeoutMs?: number) => {
  const controller = new AbortController();
  let timeoutId: number | null = null;
  let timedOut = false;

  const handleSourceAbort = () => controller.abort(sourceSignal?.reason);

  if (sourceSignal) {
    if (sourceSignal.aborted) {
      controller.abort(sourceSignal.reason);
    } else {
      sourceSignal.addEventListener("abort", handleSourceAbort, { once: true });
    }
  }

  if (timeoutMs && timeoutMs > 0) {
    timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort(new DOMException("Request timed out.", "TimeoutError"));
    }, timeoutMs);
  }

  const clearTimeoutOnly = () => {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
      timeoutId = null;
    }
  };

  return {
    signal: controller.signal,
    clearTimeout: clearTimeoutOnly,
    cleanup: () => {
      clearTimeoutOnly();
      if (sourceSignal) {
        sourceSignal.removeEventListener("abort", handleSourceAbort);
      }
    },
    didTimeout: () => timedOut,
  };
};

const parseErrorPayload = async (response: Response) => {
  const contentType = response.headers.get("content-type");
  const requestId = response.headers.get("X-Request-ID") || "-";

  if (isJsonResponse(contentType)) {
    try {
      const payload = (await response.json()) as Partial<ApiErrorResponse>;
      return new ApiError({
        status: response.status,
        detail: payload.detail || `Request failed with status ${response.status}.`,
        requestId: payload.request_id || requestId,
        upstreamError: payload.upstream_error ?? null,
      });
    } catch {
      return new ApiError({
        status: response.status,
        detail: `Request failed with status ${response.status}.`,
        requestId,
      });
    }
  }

  const detail = (await response.text()) || `Request failed with status ${response.status}.`;
  return new ApiError({
    status: response.status,
    detail,
    requestId,
  });
};

async function requestJson<T>(
  path: string,
  init?: RequestInit,
  options?: { allowEmpty?: boolean; timeoutMs?: number },
): Promise<T> {
  const requestSignal = createTimedSignal(
    init?.signal,
    options?.timeoutMs ?? DEFAULT_JSON_REQUEST_TIMEOUT_MS,
  );

  try {
    const response = await fetch(buildApiUrl(path), {
      ...init,
      signal: requestSignal.signal,
      headers: {
        Accept: "application/json",
        ...(init?.body instanceof FormData
          ? {}
          : {
              "Content-Type": "application/json",
            }),
        ...(init?.headers || {}),
      },
    });

    if (!response.ok) {
      throw await parseErrorPayload(response);
    }

    if (response.status === 204 || options?.allowEmpty) {
      return undefined as T;
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (isAbortError(error) && init?.signal?.aborted && !requestSignal.didTimeout()) {
      throw error;
    }
    throw buildUnavailableApiError();
  } finally {
    requestSignal.cleanup();
  }
}

export const getHealth = () => requestJson<HealthResponse>("/health");

export const getDeepHealth = () => requestJson<DeepHealthResponse>("/health/deep");

export const listConversations = () =>
  requestJson<ConversationSummary[]>("/chat/conversations");

export const getConversation = (conversationId: string) =>
  requestJson<ConversationDetail>(`/chat/conversations/${conversationId}`);

export const renameConversation = (
  conversationId: string,
  payload: ConversationRenameRequest,
) =>
  requestJson<ConversationSummary>(`/chat/conversations/${conversationId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const deleteConversation = (conversationId: string) =>
  requestJson<void>(
    `/chat/conversations/${conversationId}`,
    { method: "DELETE" },
    { allowEmpty: true },
  );

export const cancelConversationMessage = (conversationId: string, messageId: string) =>
  requestJson<CancelMessageResponse>(
    `/chat/conversations/${conversationId}/messages/${messageId}/cancel`,
    {
      method: "POST",
    },
  );

export async function uploadChatFile(file: File, signal?: AbortSignal) {
  const formData = new FormData();
  formData.append("file", file);

  return requestJson<ChatUploadResponse>(
    "/chat/uploads",
    {
      method: "POST",
      body: formData,
      signal,
    },
    { timeoutMs: FILE_UPLOAD_TIMEOUT_MS },
  );
}

export const deleteUpload = (uploadId: string) =>
  requestJson<void>(`/chat/uploads/${uploadId}`, { method: "DELETE" }, { allowEmpty: true });

export async function* streamChat(
  payload: ChatStreamRequest,
  signal: AbortSignal,
): AsyncGenerator<ChatStreamEvent, void, void> {
  yield* streamNdjson("/chat/stream", payload, signal);
}

export async function* editConversationMessageStream(
  conversationId: string,
  messageId: string,
  payload: EditMessageStreamRequest,
  signal: AbortSignal,
): AsyncGenerator<ChatStreamEvent, void, void> {
  yield* streamNdjson(
    `/chat/conversations/${conversationId}/messages/${messageId}/edit-stream`,
    payload,
    signal,
  );
}

export async function* regenerateConversationMessageStream(
  conversationId: string,
  messageId: string,
  payload: RegenerateMessageStreamRequest,
  signal: AbortSignal,
): AsyncGenerator<ChatStreamEvent, void, void> {
  yield* streamNdjson(
    `/chat/conversations/${conversationId}/messages/${messageId}/regenerate-stream`,
    payload,
    signal,
  );
}

async function* streamNdjson(
  path: string,
  payload: ChatStreamRequest | EditMessageStreamRequest | RegenerateMessageStreamRequest,
  signal: AbortSignal,
): AsyncGenerator<ChatStreamEvent, void, void> {
  const streamSignal = createTimedSignal(signal, STREAM_CONNECT_TIMEOUT_MS);
  let sawFirstEvent = false;

  try {
    const response = await fetch(buildApiUrl(path), {
      method: "POST",
      headers: {
        Accept: "application/x-ndjson",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: streamSignal.signal,
    });

    if (!response.ok) {
      throw await parseErrorPayload(response);
    }

    if (!response.body) {
      throw new ApiError({
        status: 500,
        detail: EMPTY_STREAM_BODY_MESSAGE,
        requestId: response.headers.get("X-Request-ID") || "-",
      });
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });

        while (true) {
          const newlineIndex = buffer.indexOf("\n");
          if (newlineIndex < 0) {
            break;
          }

          const line = buffer.slice(0, newlineIndex).trim();
          buffer = buffer.slice(newlineIndex + 1);

          if (!line) {
            continue;
          }

          if (!sawFirstEvent) {
            sawFirstEvent = true;
            streamSignal.clearTimeout();
          }
          yield JSON.parse(line) as ChatStreamEvent;
        }
      }

      const tail = `${buffer}${decoder.decode()}`.trim();
      if (tail) {
        if (!sawFirstEvent) {
          sawFirstEvent = true;
          streamSignal.clearTimeout();
        }
        yield JSON.parse(tail) as ChatStreamEvent;
      }
    } finally {
      reader.releaseLock();
    }
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (isAbortError(error) && signal.aborted && !streamSignal.didTimeout()) {
      throw error;
    }
    throw buildUnavailableApiError();
  } finally {
    streamSignal.cleanup();
  }
}
