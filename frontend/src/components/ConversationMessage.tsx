import { Suspense, lazy, memo } from "react";
import { extractAssistantDisplayContent } from "../utils/assistantContent";
import { getMessageText, type DisplayImagePart, type DisplayMessage } from "../features/chat/model";

const MarkdownRenderer = lazy(() => import("./MarkdownRenderer"));
const ThinkingBox = lazy(() => import("./ThinkingBox"));

export type ConversationMessageProps = {
  message: DisplayMessage;
  isStreaming: boolean;
  previousUserText?: string;
};

export const formatThoughtSummary = (
  createdAt: string,
  updatedAt: string,
  thinkingCompletedAt: string | null | undefined,
  isStreaming: boolean,
) => {
  if (isStreaming) {
    return "Thinking...";
  }

  const startedAt = Date.parse(createdAt);
  const settledAt = Date.parse(thinkingCompletedAt ?? updatedAt);
  if (!Number.isFinite(startedAt) || !Number.isFinite(settledAt) || settledAt <= startedAt) {
    return "Thought complete";
  }

  const elapsedSeconds = Math.max(1, Math.round((settledAt - startedAt) / 1000));
  if (elapsedSeconds < 60) {
    return `Thought for ${elapsedSeconds} second${elapsedSeconds === 1 ? "" : "s"}`;
  }

  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = elapsedSeconds % 60;
  if (seconds === 0) {
    return `Thought for ${minutes} minute${minutes === 1 ? "" : "s"}`;
  }

  return `Thought for ${minutes} minute${minutes === 1 ? "" : "s"} ${seconds} second${seconds === 1 ? "" : "s"}`;
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
}: ConversationMessageProps) => {
  const text = getMessageText(message);
  const images = message.parts.filter((part): part is DisplayImagePart => part.type === "image");

  if (message.role === "user") {
    const hasText = text.trim().length > 0;

    return (
      <div className="message-user-shell max-w-[85%] whitespace-pre-wrap break-words text-[16px] text-right sm:max-w-[30rem]">
        {renderMessageImages(images, hasText, message.role)}
        {hasText ? text : null}
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
    <div className={assistantDisplay.hasThinking ? "w-full max-w-[44rem]" : "max-w-[85%] sm:max-w-[44rem]"}>
      {message.model ? (
        <div className="mb-3 text-[13px] font-medium tracking-[-0.01em] text-[#dbe7ff]/88">
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
    </div>
  );
};

const ConversationMessage = memo(ConversationMessageComponent);

ConversationMessage.displayName = "ConversationMessage";

export default ConversationMessage;
