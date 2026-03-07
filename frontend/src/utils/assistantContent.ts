export type AssistantDisplayContent = {
  answerText: string;
  thinkingText: string;
  hasThinking: boolean;
  thinkingComplete: boolean;
};

const THINK_OPEN_TOKEN = "<think>";
const THINK_CLOSE_TOKEN = "</think>";
const TRANSCRIPT_ROLE_PATTERN =
  "(?:user|assistant|model|system|\\u7528\\u6237|\\u52a9\\u624b|\\u6a21\\u578b|\\u7cfb\\u7edf)";

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const stripLeadingEchoedPrompt = (answerText: string, previousUserText: string) => {
  const normalizedPrompt = previousUserText.trim();
  if (!normalizedPrompt) {
    return answerText;
  }

  const promptPattern = escapeRegExp(normalizedPrompt);
  const repeatedPromptPattern = new RegExp(
    `^(?:\\s*(?:${promptPattern}|${TRANSCRIPT_ROLE_PATTERN}\\s*[:：]\\s*${promptPattern})\\s*)+`,
    "iu",
  );
  const transcriptPattern = new RegExp(
    `^(?:\\s*${TRANSCRIPT_ROLE_PATTERN}\\s*[:：]\\s*)+`,
    "iu",
  );

  let next = answerText;
  let changed = true;

  while (changed) {
    changed = false;

    const withoutPrompt = next.replace(repeatedPromptPattern, "");
    if (withoutPrompt !== next) {
      next = withoutPrompt.replace(/^\s+/, "");
      changed = true;
      continue;
    }

    const withoutTranscriptPrefix = next.replace(transcriptPattern, "");
    if (withoutTranscriptPrefix !== next) {
      next = withoutTranscriptPrefix.replace(/^\s+/, "");
      changed = true;
    }
  }

  return next;
};

export const extractAssistantDisplayContent = (
  content: string,
  previousUserText = "",
): AssistantDisplayContent => {
  if (!content) {
    return {
      answerText: "",
      thinkingText: "",
      hasThinking: false,
      thinkingComplete: true,
    };
  }

  const answerSegments: string[] = [];
  const thinkingSegments: string[] = [];
  const lowerContent = content.toLowerCase();
  let cursor = 0;
  let thinkingComplete = true;

  while (cursor < content.length) {
    const openIndex = lowerContent.indexOf(THINK_OPEN_TOKEN, cursor);
    if (openIndex < 0) {
      answerSegments.push(content.slice(cursor));
      break;
    }

    answerSegments.push(content.slice(cursor, openIndex));

    const thinkingStart = openIndex + THINK_OPEN_TOKEN.length;
    const closeIndex = lowerContent.indexOf(THINK_CLOSE_TOKEN, thinkingStart);
    if (closeIndex < 0) {
      thinkingSegments.push(content.slice(thinkingStart));
      thinkingComplete = false;
      break;
    }

    thinkingSegments.push(content.slice(thinkingStart, closeIndex));
    cursor = closeIndex + THINK_CLOSE_TOKEN.length;
  }

  const hasThinking = lowerContent.includes(THINK_OPEN_TOKEN);
  const thinkingText = thinkingSegments.join("\n\n").trim();
  const sanitizedAnswerText = stripLeadingEchoedPrompt(answerSegments.join(""), previousUserText);
  const answerText = `${hasThinking ? sanitizedAnswerText.replace(/^\s+/, "") : sanitizedAnswerText}`.replace(
    /\n{3,}/g,
    "\n\n",
  );

  return {
    answerText,
    thinkingText,
    hasThinking,
    thinkingComplete,
  };
};
