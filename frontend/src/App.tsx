import {
  useEffect,
  useMemo,
  useRef,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { LayoutGroup } from "framer-motion";
import { ChevronLeft } from "lucide-react";
import ChatViewport from "./components/chat/ChatViewport";
import ComposerPanel from "./components/chat/ComposerPanel";
import MobileHistorySheet from "./components/chat/MobileHistorySheet";
import SidebarHistory from "./components/chat/SidebarHistory";
import { SIDEBAR_WIDTH, describeError, hasSendableContent } from "./features/chat/model";
import { useChatStreamController } from "./hooks/useChatStreamController";
import { useComposerController } from "./hooks/useComposerController";
import { useConversationController } from "./hooks/useConversationController";
import { ApiError } from "./services/api";

function App() {
  const viewportRef = useRef<HTMLDivElement>(null);
  const conversation = useConversationController();
  const composer = useComposerController();
  const stream = useChatStreamController({
    composer,
    conversation,
  });
  const focusInput = composer.focusInput;
  const hasSendableDraft = hasSendableContent(composer.input, composer.pendingUploads);
  const canSubmit =
    !stream.isBusy &&
    !composer.hasUploadingUploads &&
    !composer.hasErroredUploads &&
    hasSendableDraft;
  const submitButtonLabel = stream.isBusy
    ? "Busy"
    : composer.hasUploadingUploads
      ? "Wait"
      : composer.hasErroredUploads
        ? "Fix"
        : "Send";
  const submitButtonTitle = stream.isBusy
    ? "Wait for the current response to finish."
    : composer.hasUploadingUploads
      ? "Wait for image uploads to finish before sending."
      : composer.hasErroredUploads
        ? "Retry or remove failed images before sending."
        : hasSendableDraft
          ? "Send message"
          : "Type a message or attach an image to send.";

  const shellStyle = useMemo(
    () =>
      ({
        "--sidebar-width": `${conversation.sidebarCollapsed ? 0 : SIDEBAR_WIDTH}px`,
      }) as CSSProperties,
    [conversation.sidebarCollapsed],
  );

  useEffect(() => {
    focusInput();
  }, [conversation.activeConversationId, focusInput]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !conversation.stickToBottom) {
      return;
    }

    viewport.scrollTo({
      top: viewport.scrollHeight,
      behavior: stream.isBusy ? "auto" : "smooth",
    });
  }, [
    conversation.activeConversationId,
    conversation.currentMessages,
    conversation.stickToBottom,
    stream.isBusy,
  ]);

  const setActionError = (error: unknown, fallback: string) => {
    composer.setMotionSource("system");
    composer.setComposerError({
      message: describeError(error, fallback),
      retryable: error instanceof ApiError ? error.retryable : true,
    });
  };

  const handleSelectConversation = async (conversationId: string) => {
    try {
      await conversation.selectConversation(conversationId, { isBusy: stream.isBusy });
    } catch (error) {
      setActionError(error, "Failed to load conversation.");
    }
  };

  const handleStartNewChat = () => {
    if (stream.isBusy) {
      return;
    }

    composer.resetComposer({ deleteRemoteUploads: true });
    conversation.openDraftConversation();
    focusInput();
  };

  const handleDeleteConversation = async (conversationId: string) => {
    try {
      await conversation.deleteConversation(conversationId, { isBusy: stream.isBusy });
    } catch (error) {
      setActionError(error, "Failed to delete conversation.");
    }
  };

  const handleRetryScreen = () => {
    window.location.reload();
  };

  const handleScroll = () => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }

    const distanceFromBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    conversation.setStickToBottom(distanceFromBottom < 72);
  };

  const handleTextareaKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape" && stream.isBusy) {
      event.preventDefault();
      void stream.handleStop();
      return;
    }

    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }

    event.preventDefault();
    void stream.sendPrompt();
  };

  const handleSubmit = () => {
    if (!canSubmit) {
      return;
    }

    void stream.sendPrompt();
  };

  return (
    <div className="min-h-screen bg-[#050608] text-white" style={shellStyle}>
      <LayoutGroup>
        <SidebarHistory
          conversations={conversation.conversations}
          activeConversationId={conversation.activeConversationId}
          deleteConfirmId={conversation.deleteConfirmId}
          recentBornConversationId={conversation.recentBornConversationId}
          sidebarCollapsed={conversation.sidebarCollapsed}
          isBusy={stream.isBusy}
          isDraftSelected={conversation.isDraftSelected}
          isMetaPendingDraft={stream.isMetaPendingDraft}
          motionSource={conversation.historyMotionSource}
          onToggleCollapse={conversation.toggleDesktopSidebar}
          onStartNewChat={handleStartNewChat}
          onSelectConversation={(conversationId) => void handleSelectConversation(conversationId)}
          onDeleteConversation={(conversationId) => void handleDeleteConversation(conversationId)}
          onCancelDelete={conversation.clearDeleteConfirmation}
        />

        <MobileHistorySheet
          conversations={conversation.conversations}
          activeConversationId={conversation.activeConversationId}
          deleteConfirmId={conversation.deleteConfirmId}
          isOpen={conversation.isSidebarOpen}
          isBusy={stream.isBusy}
          isDraftSelected={conversation.isDraftSelected}
          isMetaPendingDraft={stream.isMetaPendingDraft}
          motionSource={conversation.historyMotionSource}
          onClose={conversation.closeMobileSidebar}
          onStartNewChat={handleStartNewChat}
          onSelectConversation={(conversationId) => void handleSelectConversation(conversationId)}
          onDeleteConversation={(conversationId) => void handleDeleteConversation(conversationId)}
          onCancelDelete={conversation.clearDeleteConfirmation}
        />

        <main className="desktop-main flex min-h-screen flex-col">
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-4 md:hidden">
            <button
              type="button"
              aria-label="Open sidebar"
              aria-haspopup="dialog"
              aria-expanded={conversation.isSidebarOpen}
              className="sidebar-collapse-trigger"
              onClick={conversation.openMobileSidebar}
            >
              <ChevronLeft className="h-4 w-4 -rotate-90" strokeWidth={1.8} />
            </button>
            <span className="max-w-[12rem] truncate text-xs uppercase tracking-[0.26em] text-zinc-500">
              {conversation.activeTitle}
            </span>
            <div className="w-8" />
          </div>

          <ChatViewport
            viewportRef={viewportRef}
            currentMessages={conversation.currentMessages}
            activeConversationId={conversation.activeConversationId}
            activeConversation={conversation.activeConversation}
            loadingConversationId={conversation.loadingConversationId}
            screenError={conversation.screenError}
            phase={stream.phase}
            sceneKey={conversation.viewportSceneKey}
            motionSource={conversation.viewportMotionSource}
            onScroll={handleScroll}
            onRetryScreen={handleRetryScreen}
          />
        </main>

        <ComposerPanel
          phase={stream.phase}
          composerError={composer.composerError}
          input={composer.input}
          pendingUploads={composer.pendingUploads}
          isInputFocused={composer.isInputFocused}
          dragActive={composer.dragActive}
          inputRippleKey={composer.inputRippleKey}
          isMobileSidebarOpen={conversation.isSidebarOpen}
          motionSource={stream.isBusy ? "stream" : composer.motionSource}
          textareaRef={composer.textareaRef}
          fileInputRef={composer.fileInputRef}
          onRetryComposerError={stream.handleRetry}
          onStop={() => void stream.handleStop()}
          onOpenFilePicker={composer.openFilePicker}
          onFileChange={(event) => composer.handleFileChange(event, { isBusy: stream.isBusy })}
          onTextareaChange={composer.handleInputChange}
          onTextareaFocus={() => {
            composer.setIsInputFocused(true);
            composer.setInputRippleKey((current) => current + 1);
          }}
          onTextareaBlur={() => composer.setIsInputFocused(false)}
          onTextareaKeyDown={handleTextareaKeyDown}
          onTextareaPaste={(event) => composer.handleComposerPaste(event, { isBusy: stream.isBusy })}
          onRemoveUpload={(localId) => void composer.removeUpload(localId)}
          onRetryUpload={composer.retryUpload}
          onDragEnter={(event) => composer.handleDragEnter(event, { isBusy: stream.isBusy })}
          onDragOver={(event) => composer.handleDragOver(event, { isBusy: stream.isBusy })}
          onDragLeave={composer.handleDragLeave}
          onDrop={(event) => composer.handleDrop(event, { isBusy: stream.isBusy })}
          canSubmit={canSubmit}
          submitButtonLabel={submitButtonLabel}
          submitButtonTitle={submitButtonTitle}
          onSubmit={handleSubmit}
        />
      </LayoutGroup>
    </div>
  );
}

export default App;
