import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  MOTION_SPRING,
  MOTION_TRANSITION,
  getSceneTransition,
  shouldAnimateLayout,
  type MotionSource,
} from "../../motion/tokens";
import type { AppPhase, ComposerError, PendingUpload } from "../../features/chat/model";

const AddImageIcon = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 337 337"
    className="composer-upload-icon"
    aria-hidden="true"
  >
    <circle strokeWidth="20" stroke="#6c6c6c" fill="none" r="158.5" cy="168.5" cx="168.5" />
    <path strokeLinecap="round" strokeWidth="25" stroke="#6c6c6c" d="M167.759 79V259" />
    <path strokeLinecap="round" strokeWidth="25" stroke="#6c6c6c" d="M79 167.138H259" />
  </svg>
);

const SendIcon = () => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 664 663"
    className="composer-send-icon"
    aria-hidden="true"
  >
    <path
      fill="none"
      d="M646.293 331.888L17.7538 17.6187L155.245 331.888M646.293 331.888L17.753 646.157L155.245 331.888M646.293 331.888L318.735 330.228L155.245 331.888"
    />
    <path
      strokeLinejoin="round"
      strokeLinecap="round"
      strokeWidth="33.67"
      stroke="#6c6c6c"
      d="M646.293 331.888L17.7538 17.6187L155.245 331.888M646.293 331.888L17.753 646.157L155.245 331.888M646.293 331.888L318.735 330.228L155.245 331.888"
    />
  </svg>
);

type ComposerPanelProps = {
  phase: AppPhase;
  composerError: ComposerError | null;
  input: string;
  pendingUploads: PendingUpload[];
  isInputFocused: boolean;
  isEditingMessage: boolean;
  dragActive: boolean;
  inputRippleKey: number;
  isMobileSidebarOpen: boolean;
  motionSource: MotionSource;
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  fileInputRef: React.RefObject<HTMLInputElement>;
  onRetryComposerError: () => void;
  onStop: () => void;
  onCancelEdit: () => void;
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
  isEditingMessage,
  dragActive,
  isMobileSidebarOpen,
  motionSource,
  textareaRef,
  fileInputRef,
  onRetryComposerError,
  onStop,
  onCancelEdit,
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
  const showEditState = isEditingMessage && !showThinkingState;
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

          <motion.div
            className="composer-shell relative"
            layout={shellLayout}
            transition={shouldAnimateLayout(motionSource) ? MOTION_SPRING.panel : MOTION_TRANSITION.soft}
            onDragEnter={onDragEnter}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
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

            <div className="composer-message-region">
              <div className={`messageBox ${isInputFocused ? "is-focused" : ""} ${dragActive ? "is-dragging" : ""}`}>
                <AnimatePresence initial={false} mode="popLayout">
                  {showThinkingState ? (
                    <motion.div
                      key="composer-status"
                      className="composer-inline-status-row"
                      initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -4 }}
                      transition={presenceTransition}
                    >
                      <div className="composer-inline-status" role="status" aria-live="polite">
                        <span className="thinking-pulse" aria-hidden="true" />
                        <span>{isStopping ? "Stopping..." : "Thinking..."}</span>
                      </div>
                      <motion.button
                        type="button"
                        className="composer-inline-stop"
                        onClick={onStop}
                        disabled={isStopping}
                      >
                        Stop
                      </motion.button>
                    </motion.div>
                  ) : null}
                </AnimatePresence>

                <AnimatePresence initial={false} mode="popLayout">
                  {showEditState ? (
                    <motion.div
                      key="composer-editing"
                      className="composer-inline-status-row"
                      initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -4 }}
                      transition={presenceTransition}
                    >
                      <div className="composer-inline-status" role="status" aria-live="polite">
                        <span className="composer-edit-indicator" aria-hidden="true" />
                        <span>Editing last message</span>
                      </div>
                      <button type="button" className="composer-inline-stop" onClick={onCancelEdit}>
                        Cancel
                      </button>
                    </motion.div>
                  ) : null}
                </AnimatePresence>

                <div className="composer-input-row">
                  <div className="fileUploadWrapper shrink-0">
                    <motion.button
                      type="button"
                      aria-label="Add image"
                      className="composer-tool-button"
                      onClick={onOpenFilePicker}
                      disabled={isStopping || isEditingMessage}
                    >
                      <AddImageIcon />
                      <span className="tooltip">
                        {isEditingMessage ? "Images disabled while editing" : "Add an image"}
                      </span>
                    </motion.button>
                  </div>
                  <textarea
                    ref={textareaRef}
                    rows={1}
                    value={input}
                    placeholder={isEditingMessage ? "Edit the last user message" : "Message AI"}
                    aria-label="Message AI"
                    enterKeyHint="send"
                    className="composer-message-input"
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
                  >
                    <SendIcon />
                  </motion.button>
                </div>
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
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
};

export default ComposerPanel;
