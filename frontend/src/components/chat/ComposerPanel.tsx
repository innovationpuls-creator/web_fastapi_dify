import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowUp, Plus } from "lucide-react";
import {
  MOTION_SPRING,
  MOTION_TRANSITION,
  getSceneTransition,
  shouldAnimateLayout,
  type MotionSource,
} from "../../motion/tokens";
import type { AppPhase, ComposerError, PendingUpload } from "../../features/chat/model";

type ComposerPanelProps = {
  phase: AppPhase;
  composerError: ComposerError | null;
  input: string;
  pendingUploads: PendingUpload[];
  isInputFocused: boolean;
  dragActive: boolean;
  inputRippleKey: number;
  isMobileSidebarOpen: boolean;
  motionSource: MotionSource;
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  fileInputRef: React.RefObject<HTMLInputElement>;
  onRetryComposerError: () => void;
  onStop: () => void;
  onOpenFilePicker: () => void;
  onFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onTextareaChange: (value: string) => void;
  onTextareaFocus: () => void;
  onTextareaBlur: () => void;
  onTextareaKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onTextareaPaste: (event: React.ClipboardEvent<HTMLTextAreaElement>) => void;
  onRemoveUpload: (localId: string) => void;
  onRetryUpload: (localId: string) => void;
  onDragEnter: (event: React.DragEvent<HTMLDivElement>) => void;
  onDragOver: (event: React.DragEvent<HTMLDivElement>) => void;
  onDragLeave: (event: React.DragEvent<HTMLDivElement>) => void;
  onDrop: (event: React.DragEvent<HTMLDivElement>) => void;
  canSubmit: boolean;
  submitButtonLabel: string;
  submitButtonTitle: string;
  onSubmit: () => void;
};

const ComposerPanel = ({
  phase,
  composerError,
  input,
  pendingUploads,
  isInputFocused,
  dragActive,
  inputRippleKey,
  isMobileSidebarOpen,
  motionSource,
  textareaRef,
  fileInputRef,
  onRetryComposerError,
  onStop,
  onOpenFilePicker,
  onFileChange,
  onTextareaChange,
  onTextareaFocus,
  onTextareaBlur,
  onTextareaKeyDown,
  onTextareaPaste,
  onRemoveUpload,
  onRetryUpload,
  onDragEnter,
  onDragOver,
  onDragLeave,
  onDrop,
  canSubmit,
  submitButtonLabel,
  submitButtonTitle,
  onSubmit,
}: ComposerPanelProps) => {
  const reduceMotion = useReducedMotion();
  const isStopping = phase === "stopping";
  const showThinkingState = phase === "streaming" || phase === "stopping";
  const shellLayout = shouldAnimateLayout(motionSource) ? "position" : false;
  const presenceTransition = getSceneTransition(motionSource, Boolean(reduceMotion));

  return (
    <div
      className="desktop-composer pointer-events-none fixed inset-x-0 bottom-0 z-20"
      style={{
        bottom: isMobileSidebarOpen ? "calc(min(65vh, 34rem) + 0.75rem)" : undefined,
      }}
    >
      <div className="mx-auto w-full max-w-[600px] px-4 pb-6">
        <div className="pointer-events-auto">
          <AnimatePresence initial={false} mode="popLayout">
            {composerError ? (
              <motion.div
                key="composer-error"
                className="composer-error-bar mb-3 flex items-center justify-between gap-3"
                role="alert"
                aria-live="assertive"
                initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.992 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.992 }}
                transition={presenceTransition}
              >
                <span>{composerError.message}</span>
                {composerError.retryable ? (
                  <button type="button" className="composer-error-action" onClick={onRetryComposerError}>
                    Retry
                  </button>
                ) : null}
              </motion.div>
            ) : null}
          </AnimatePresence>

          <div className="mb-3 flex min-h-5 items-center justify-between gap-3">
            <AnimatePresence initial={false} mode="popLayout">
              {showThinkingState ? (
                <motion.div
                  key={phase}
                  className="thinking-status"
                  role="status"
                  aria-live="polite"
                  initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -4 }}
                  transition={presenceTransition}
                >
                  <span className="thinking-pulse" aria-hidden="true" />
                  <span>{isStopping ? "Stopping..." : "Thinking..."}</span>
                </motion.div>
              ) : (
                <div className="h-5" />
              )}
            </AnimatePresence>

            <AnimatePresence initial={false}>
              {showThinkingState ? (
                <motion.button
                  key="stop"
                  type="button"
                  className="text-[11px] uppercase tracking-[0.28em] text-zinc-500 transition hover:text-zinc-100 disabled:opacity-40"
                  onClick={onStop}
                  disabled={isStopping}
                  initial={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 8 }}
                  transition={presenceTransition}
                >
                  Stop
                </motion.button>
              ) : null}
            </AnimatePresence>
          </div>

          <motion.div
            className={`composer-shell relative rounded-[1.75rem] px-4 py-4 sm:px-5 ${
              isInputFocused ? "is-focused" : ""
            } ${dragActive ? "is-dragging" : ""}`}
            layout={shellLayout}
            transition={shouldAnimateLayout(motionSource) ? MOTION_SPRING.panel : MOTION_TRANSITION.soft}
            onDragEnter={onDragEnter}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            {inputRippleKey > 0 ? <span key={inputRippleKey} className="input-ripple" aria-hidden="true" /> : null}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              className="hidden"
              onChange={onFileChange}
            />

            <AnimatePresence initial={false}>
              {pendingUploads.length > 0 ? (
                <motion.div
                  key="pending-uploads"
                  layout={shellLayout}
                  className="mb-3 flex flex-wrap gap-2"
                  initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -8 }}
                  transition={presenceTransition}
                >
                  {pendingUploads.map((upload) => (
                    <motion.div
                      key={upload.localId}
                      layout={shellLayout}
                      className="pending-upload"
                      initial={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: 8 }}
                      animate={{ opacity: 1, scale: 1, y: 0 }}
                      exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: -6 }}
                      transition={shouldAnimateLayout(motionSource) ? MOTION_SPRING.list : MOTION_TRANSITION.soft}
                    >
                      <img
                        src={upload.previewUrl}
                        alt={`Preview of ${upload.file.name}`}
                        className="pending-upload-image"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm text-white">{upload.file.name}</div>
                        <div className="pending-upload-status">
                          {upload.status === "uploading"
                            ? "Uploading..."
                            : upload.status === "error"
                              ? upload.error || "Upload failed"
                              : `${Math.max(1, Math.round(upload.byteSize / 1024))} KB`}
                        </div>
                      </div>
                      {upload.status === "error" ? (
                        <button
                          type="button"
                          className="pending-upload-remove"
                          onClick={() => onRetryUpload(upload.localId)}
                        >
                          Retry
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="pending-upload-remove"
                        onClick={() => onRemoveUpload(upload.localId)}
                      >
                        Remove
                      </button>
                    </motion.div>
                  ))}
                </motion.div>
              ) : null}
            </AnimatePresence>

            <div className="flex items-end gap-3">
              <motion.button
                type="button"
                aria-label="Add image"
                className="composer-tool-button shrink-0"
                onClick={onOpenFilePicker}
                disabled={isStopping}
                whileTap={reduceMotion ? undefined : { scale: 0.94 }}
              >
                <Plus className="h-4 w-4" strokeWidth={1.8} />
              </motion.button>
              <textarea
                ref={textareaRef}
                rows={1}
                value={input}
                placeholder="Message AI"
                aria-label="Message AI"
                enterKeyHint="send"
                className="w-full resize-none bg-transparent py-1 text-[16px] leading-8 text-white outline-none placeholder:text-zinc-600 disabled:cursor-not-allowed disabled:opacity-70"
                disabled={isStopping}
                onChange={(event) => onTextareaChange(event.target.value)}
                onFocus={onTextareaFocus}
                onBlur={onTextareaBlur}
                onKeyDown={onTextareaKeyDown}
                onPaste={onTextareaPaste}
              />
              <motion.button
                type="button"
                aria-label={submitButtonLabel}
                className="composer-send-button shrink-0"
                onClick={onSubmit}
                disabled={!canSubmit}
                title={submitButtonTitle}
                whileTap={reduceMotion || !canSubmit ? undefined : { scale: 0.97 }}
              >
                <ArrowUp className="h-4 w-4" strokeWidth={2.1} />
                <span>{submitButtonLabel}</span>
              </motion.button>
            </div>

            <AnimatePresence initial={false}>
              {dragActive ? (
                <motion.div
                  key="composer-drop-indicator"
                  className="composer-drop-indicator"
                  initial={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.985 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.99 }}
                  transition={presenceTransition}
                >
                  Drop image to attach
                </motion.div>
              ) : null}
            </AnimatePresence>
          </motion.div>
        </div>
      </div>
    </div>
  );
};

export default ComposerPanel;
