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
