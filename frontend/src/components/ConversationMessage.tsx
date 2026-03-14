import { Suspense, lazy, memo } from "react";
import { extractAssistantDisplayContent } from "../utils/assistantContent";
import { getMessageText, type DisplayImagePart, type DisplayMessage } from "../features/chat/model";
import { formatThoughtSummary } from "./conversationMessageUtils";

const MarkdownRenderer = lazy(() => import("./MarkdownRenderer"));
const ThinkingBox = lazy(() => import("./ThinkingBox"));

export type ConversationMessageProps = {
  message: DisplayMessage;
  isStreaming: boolean;
  previousUserText?: string;
  showEdit?: boolean;
  showRegenerate?: boolean;
  onEdit?: () => void;
  onRegenerate?: () => void;
};

const formatLatency = (latencyMs: number | null | undefined) => {
  if (typeof latencyMs !== "number" || !Number.isFinite(latencyMs) || latencyMs <= 0) {
    return null;
  }

  return latencyMs >= 1000
    ? `${(latencyMs / 1000).toFixed(latencyMs >= 10_000 ? 0 : 1)}s`
    : `${Math.round(latencyMs)}ms`;
};

const renderMessageImages = (
  images: DisplayImagePart[],
  hasText: boolean,
  role: DisplayMessage["role"],
) => {
  if (images.length === 0) {
    return null;
  }

  return (
    <div className={`message-images ${hasText ? "mb-4" : ""}`}>
      {images.map((image, index) => (
        <img
          key={`${image.url}-${index}`}
          src={image.url}
          alt={`${role === "user" ? "User" : "Assistant"} attachment ${index + 1}`}
          className="message-image"
          loading="lazy"
        />
      ))}
    </div>
  );
};

const ConversationMessageComponent = ({
  message,
  isStreaming,
  previousUserText = "",
  showEdit = false,
  showRegenerate = false,
  onEdit,
  onRegenerate,
}: ConversationMessageProps) => {
  const text = getMessageText(message);
  const images = message.parts.filter((part): part is DisplayImagePart => part.type === "image");
  const assistantLatency = formatLatency(message.metrics?.latency_ms);

  if (message.role === "user") {
    const hasText = text.trim().length > 0;

    return (
      <div className="message-user-stack max-w-[88%] sm:max-w-[34rem]">
        <div className="message-user-shell whitespace-pre-wrap break-words text-[16px] text-right">
          {renderMessageImages(images, hasText, message.role)}
          {hasText ? text : null}
        </div>
        {showEdit ? (
          <div className="message-footer-row justify-end">
            <button
              type="button"
              className="message-footer-action"
              aria-label="Edit message"
              onClick={onEdit}
            >
              Edit
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  const assistantDisplay = extractAssistantDisplayContent(text, previousUserText);
  const answerToneClass =
    message.status === "failed"
      ? "text-red-200/90"
      : message.status === "cancelled"
        ? "text-zinc-400"
        : "text-white";
  const isTruncated = message.finish_reason === "length";
  const thoughtSummary = formatThoughtSummary(
    message.created_at,
    message.updated_at,
    message.thinking_completed_at,
    isStreaming && !assistantDisplay.thinkingComplete,
  );

  return (
    <div
      className={
        assistantDisplay.hasThinking
          ? "assistant-message-shell w-full max-w-[46rem]"
          : "assistant-message-shell max-w-[88%] sm:max-w-[46rem]"
      }
    >
      {message.model ? (
        <div className="assistant-model-label mb-3 text-[12px] font-medium tracking-[0.14em] text-[#dbe7ff]/72">
          {message.model}
        </div>
      ) : null}

      {assistantDisplay.hasThinking ? (
        <div className={assistantDisplay.answerText || images.length > 0 ? "mb-4" : ""}>
          <Suspense
            fallback={
              <div className="rounded-[1.1rem] border border-white/[0.08] bg-white/[0.02] px-4 py-3 text-[13px] leading-7 text-zinc-400">
                {thoughtSummary}
              </div>
            }
          >
            <ThinkingBox
              content={assistantDisplay.thinkingText}
              isStreaming={isStreaming && !assistantDisplay.thinkingComplete}
              isVisible={assistantDisplay.hasThinking}
              summary={thoughtSummary}
            />
          </Suspense>
        </div>
      ) : null}

      {renderMessageImages(images, assistantDisplay.answerText.length > 0, message.role)}

      {assistantDisplay.answerText ? (
        <div className="min-w-0">
          <Suspense
            fallback={
              <div className={`whitespace-pre-wrap break-words text-[16px] leading-9 ${answerToneClass}`}>
                {assistantDisplay.answerText}
              </div>
            }
          >
            <MarkdownRenderer
              content={assistantDisplay.answerText}
              toneClassName={answerToneClass}
              isStreaming={isStreaming}
            />
          </Suspense>
        </div>
      ) : message.isSkeleton && !assistantDisplay.hasThinking ? (
        <span className="assistant-cursor" aria-hidden="true" />
      ) : null}

      {isTruncated ? (
        <div className="mt-3 inline-flex rounded-full border border-amber-200/10 bg-amber-200/[0.06] px-3 py-1 text-[12px] tracking-[-0.01em] text-amber-100/70">
          Response truncated due to output limit.
        </div>
      ) : null}

      {showRegenerate ? (
        <div className="message-footer-row">
          {message.metrics?.total_tokens ? <span>Tokens: {message.metrics.total_tokens}</span> : null}
          {assistantLatency ? <span>Latency: {assistantLatency}</span> : null}
          {showRegenerate ? (
            <button
              type="button"
              className="message-footer-action"
              aria-label="Regenerate response"
              onClick={onRegenerate}
            >
              Regenerate
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};

const ConversationMessage = memo(ConversationMessageComponent);

ConversationMessage.displayName = "ConversationMessage";

export default ConversationMessage;
