import { memo, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import MarkdownRenderer from "./MarkdownRenderer";
import { MOTION_SPRING, MOTION_TRANSITION } from "../motion/tokens";

export type ThinkingBoxProps = {
  content: string;
  isStreaming: boolean;
  isVisible: boolean;
  summary: string;
};

const STREAMING_PANEL_HEIGHT_CLASS = "h-[15.5rem] sm:h-[18rem]";

const StreamingCursor = ({ reduceMotion }: { reduceMotion: boolean }) => (
  <motion.span
    aria-hidden="true"
    className="ml-1 inline-block h-[1.05em] w-[0.42rem] rounded-full bg-white/50 align-[-0.12em]"
    animate={reduceMotion ? { opacity: 0.72 } : { opacity: [0.18, 0.88, 0.18] }}
    transition={{
      duration: reduceMotion ? 0.01 : 0.92,
      ease: "easeInOut",
      repeat: reduceMotion ? 0 : Number.POSITIVE_INFINITY,
    }}
  />
);

const ThinkingBoxComponent = ({ content, isStreaming, isVisible, summary }: ThinkingBoxProps) => {
  const reduceMotion = useReducedMotion();
  const previousStreamingRef = useRef(isStreaming);
  const streamingViewportRef = useRef<HTMLDivElement | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);

  const hasContent = content.trim().length > 0;
  const showPanel = isStreaming || (hasContent && isExpanded);
  const isFixedStreamingPanel = isStreaming;
  const transition = reduceMotion ? MOTION_TRANSITION.soft : MOTION_SPRING.panel;

  useEffect(() => {
    const wasStreaming = previousStreamingRef.current;

    if (!wasStreaming && isStreaming) {
      setIsExpanded(false);
    }

    if (wasStreaming && !isStreaming) {
      // Once the stream settles we always collapse back to the summary row.
      setIsExpanded(false);
    }

    previousStreamingRef.current = isStreaming;
  }, [isStreaming]);

  useEffect(() => {
    if (!isStreaming) {
      return;
    }

    const viewport = streamingViewportRef.current;
    if (!viewport) {
      return;
    }

    const syncToLatest = () => {
      viewport.scrollTop = viewport.scrollHeight;
    };

    syncToLatest();
    const frameId = window.requestAnimationFrame(syncToLatest);

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [content, isStreaming]);

  if (!isVisible) {
    return null;
  }

  const handleToggle = () => {
    if (!hasContent || isStreaming) {
      return;
    }

    setIsExpanded((current) => !current);
  };

  return (
    <div className="w-full">
      <button
        type="button"
        onClick={handleToggle}
        disabled={!hasContent || isStreaming}
        aria-expanded={showPanel}
        className="group inline-flex w-full items-center gap-2 rounded-xl py-1 text-left text-zinc-400 transition hover:text-zinc-200 disabled:cursor-default disabled:hover:text-zinc-400"
      >
        <motion.span
          aria-hidden="true"
          animate={{ rotate: showPanel ? 90 : 0 }}
          transition={transition}
          className="flex h-4 w-4 items-center justify-center text-zinc-500"
        >
          <ChevronRight className="h-3.5 w-3.5" strokeWidth={2} />
        </motion.span>
        <span className="text-[13px] font-medium tracking-[-0.01em] sm:text-[14px]">{summary}</span>
      </button>

      <AnimatePresence initial={false}>
        {showPanel ? (
          <motion.div
            layout
            initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -6 }}
            transition={reduceMotion ? MOTION_TRANSITION.fade : MOTION_SPRING.panel}
            className="mt-2 w-full overflow-hidden rounded-[1.1rem] border border-white/[0.08] bg-[linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.015))] shadow-[inset_0_1px_0_rgba(255,255,255,0.025)]"
          >
            <div
              ref={isFixedStreamingPanel ? streamingViewportRef : null}
              className={`relative w-full px-4 py-3 text-[13px] leading-7 text-zinc-400 sm:px-5 ${
                isFixedStreamingPanel ? `${STREAMING_PANEL_HEIGHT_CLASS} overflow-y-auto` : ""
              }`}
            >
              <div className="min-w-0 break-words pr-1">
                {isStreaming ? (
                  <div className="whitespace-pre-wrap break-words">
                    {content}
                    {isStreaming ? <StreamingCursor reduceMotion={Boolean(reduceMotion)} /> : null}
                  </div>
                ) : (
                  <MarkdownRenderer
                    content={content}
                    toneClassName="text-zinc-400"
                    variant="compact"
                  />
                )}
              </div>
              {isFixedStreamingPanel ? (
                <div className="pointer-events-none absolute inset-x-0 top-0 h-10 bg-gradient-to-b from-[#17181b] via-[#17181b]/94 to-transparent" />
              ) : null}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
};

const ThinkingBox = memo(ThinkingBoxComponent);

ThinkingBox.displayName = "ThinkingBox";

export default ThinkingBox;
