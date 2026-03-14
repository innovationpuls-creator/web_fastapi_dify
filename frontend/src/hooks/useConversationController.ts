import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  deleteConversation as deleteConversationRequest,
  getConversation,
  getHealth,
  listConversations,
  renameConversation as renameConversationRequest,
  type ConversationSummary,
} from "../services/api";
import {
  EMPTY_TITLE,
  cloneConversation,
  cloneMessage,
  summaryFromDetail,
  toDisplayConversation,
  type DisplayConversation,
  type DisplayMessage,
  type ScreenError,
} from "../features/chat/model";
import {
  patchConversationDetailMessages,
  removeConversationDetail,
  removeConversationSummary,
  resolveNextConversationId,
  resolvePreferredConversationId,
  syncSummaryInList,
} from "../features/chat/conversationState";
import type { MotionSource } from "../motion/tokens";

type PatchMessageUpdater = (messages: DisplayMessage[]) => DisplayMessage[];

export const useConversationController = () => {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationDetails, setConversationDetails] = useState<Record<string, DisplayConversation>>(
    {},
  );
  const [draftMessages, setDraftMessages] = useState<DisplayMessage[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [loadingConversationId, setLoadingConversationId] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [recentBornConversationId, setRecentBornConversationId] = useState<string | null>(null);
  const [screenError, setScreenError] = useState<ScreenError | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [stickToBottom, setStickToBottom] = useState(true);
  const [viewportSceneKey, setViewportSceneKey] = useState(0);
  const [viewportMotionSource, setViewportMotionSource] = useState<MotionSource>("system");
  const [historyMotionSource, setHistoryMotionSource] = useState<MotionSource>("system");

  const conversationsRef = useRef(conversations);
  const conversationDetailsRef = useRef(conversationDetails);
  const draftMessagesRef = useRef(draftMessages);
  const activeConversationIdRef = useRef(activeConversationId);

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  useEffect(() => {
    conversationDetailsRef.current = conversationDetails;
  }, [conversationDetails]);

  useEffect(() => {
    draftMessagesRef.current = draftMessages;
  }, [draftMessages]);

  useEffect(() => {
    activeConversationIdRef.current = activeConversationId;
  }, [activeConversationId]);

  useEffect(() => {
    if (!recentBornConversationId) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      setRecentBornConversationId((current) =>
        current === recentBornConversationId ? null : current,
      );
    }, 520);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [recentBornConversationId]);

  const activeConversation = useMemo(
    () => (activeConversationId ? conversationDetails[activeConversationId] ?? null : null),
    [activeConversationId, conversationDetails],
  );

  const isDraftSelected = activeConversationId === null;
  const currentMessages = activeConversationId ? activeConversation?.messages ?? [] : draftMessages;
  const activeTitle =
    activeConversation?.title ||
    conversations.find((conversation) => conversation.id === activeConversationId)?.title ||
    EMPTY_TITLE;

  const setSceneMotion = useCallback((source: MotionSource) => {
    setViewportMotionSource(source);
    if (source === "user") {
      setViewportSceneKey((current) => current + 1);
    }
  }, []);

  const syncSummary = useCallback((summary: ConversationSummary, moveToTop = false) => {
    setConversations((current) => syncSummaryInList(current, summary, moveToTop));
  }, []);

  const syncConversation = useCallback(
    (detail: DisplayConversation, moveToTop = false) => {
      setConversationDetails((current) => ({
        ...current,
        [detail.id]: detail,
      }));
      syncSummary(summaryFromDetail(detail), moveToTop);
    },
    [syncSummary],
  );

  const patchConversationMessages = useCallback(
    (conversationId: string | null, updater: PatchMessageUpdater) => {
      if (conversationId === null) {
        setDraftMessages((current) => updater(current));
        return;
      }

      setConversationDetails((current) => {
        const detail = current[conversationId];
        if (!detail) {
          return current;
        }

        return {
          ...current,
          [conversationId]: patchConversationDetailMessages(detail, updater) as DisplayConversation,
        };
      });
    },
    [],
  );

  const removeConversationFromStore = useCallback((conversationId: string) => {
    setHistoryMotionSource("system");
    setConversations((current) => removeConversationSummary(current, conversationId));
    setConversationDetails((current) => removeConversationDetail(current, conversationId));

    if (activeConversationIdRef.current === conversationId) {
      const nextId = resolveNextConversationId(conversationsRef.current, conversationId);
      setSceneMotion("system");
      setActiveConversationId(nextId);
    }
  }, [setSceneMotion]);

  const loadConversationDetail = useCallback(
    async (conversationId: string, options?: { activate?: boolean; force?: boolean }) => {
      if (options?.activate) {
        setActiveConversationId(conversationId);
      }

      if (!options?.force && conversationDetailsRef.current[conversationId]) {
        return conversationDetailsRef.current[conversationId];
      }

      setLoadingConversationId(conversationId);

      try {
        const detail = toDisplayConversation(await getConversation(conversationId));
        syncConversation(detail);
        return detail;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          removeConversationFromStore(conversationId);
        }
        throw error;
      } finally {
        setLoadingConversationId((current) => (current === conversationId ? null : current));
      }
    },
    [removeConversationFromStore, syncConversation],
  );

  const refreshConversationList = useCallback(
    async (preferredId?: string | null) => {
      setHistoryMotionSource("system");
      const items = await listConversations();
      setConversations(items);

      const targetId = resolvePreferredConversationId(items, preferredId);

      if (targetId && !conversationDetailsRef.current[targetId]) {
        setSceneMotion("system");
        await loadConversationDetail(targetId, { activate: true });
        return;
      }

      setViewportMotionSource("system");
      setActiveConversationId(targetId);
    },
    [loadConversationDetail, setSceneMotion],
  );

  const reconcileConversation = useCallback(
    async (conversationId: string, moveToTop = false) => {
      try {
        setHistoryMotionSource("system");
        const detail = toDisplayConversation(await getConversation(conversationId));
        syncConversation(detail, moveToTop);
        return detail;
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          removeConversationFromStore(conversationId);
        }
        throw error;
      }
    },
    [removeConversationFromStore, syncConversation],
  );

  const prepareForNavigation = useCallback((source: MotionSource = "user") => {
    setDeleteConfirmId(null);
    setScreenError(null);
    setIsSidebarOpen(false);
    setStickToBottom(true);
    setHistoryMotionSource(source);
    setSceneMotion(source);
  }, [setSceneMotion]);

  const selectConversation = useCallback(
    async (conversationId: string, options?: { isBusy?: boolean }) => {
      if (options?.isBusy) {
        return;
      }

      if (activeConversationIdRef.current !== conversationId) {
        prepareForNavigation("user");
      } else {
        setHistoryMotionSource("user");
        setDeleteConfirmId(null);
        setScreenError(null);
        setIsSidebarOpen(false);
        setStickToBottom(true);
      }
      setActiveConversationId(conversationId);
      await loadConversationDetail(conversationId, { activate: true });
    },
    [loadConversationDetail, prepareForNavigation],
  );

  const openDraftConversation = useCallback(() => {
    prepareForNavigation("user");
    setDraftMessages([]);
    setActiveConversationId(null);
    setLoadingConversationId(null);
    setRecentBornConversationId(null);
  }, [prepareForNavigation]);

  const markConversationBorn = useCallback((conversationId: string) => {
    setHistoryMotionSource("user");
    setRecentBornConversationId(conversationId);
  }, []);

  const restoreDraftMessages = useCallback((messages: DisplayMessage[]) => {
    setDraftMessages(messages.map(cloneMessage));
  }, []);

  const restoreConversationSnapshot = useCallback((conversation: DisplayConversation | null) => {
    if (!conversation) {
      return;
    }

    setConversationDetails((current) => ({
      ...current,
      [conversation.id]: cloneConversation(conversation) as DisplayConversation,
    }));
  }, []);

  const clearDeleteConfirmation = useCallback(() => {
    setDeleteConfirmId(null);
  }, []);

  const deleteConversation = useCallback(
    async (conversationId: string, options?: { isBusy?: boolean }) => {
      if (options?.isBusy) {
        return;
      }

      setHistoryMotionSource("user");
      await deleteConversationRequest(conversationId);
      setDeleteConfirmId(null);
      setConversations((current) => removeConversationSummary(current, conversationId));
      setConversationDetails((current) => removeConversationDetail(current, conversationId));

      if (activeConversationIdRef.current === conversationId) {
        const nextId = resolveNextConversationId(conversationsRef.current, conversationId);
        setSceneMotion("user");
        setActiveConversationId(nextId);

        if (nextId) {
          await loadConversationDetail(nextId, { activate: true });
        } else {
          setDraftMessages([]);
          setLoadingConversationId(null);
        }
      }
    },
    [loadConversationDetail, setSceneMotion],
  );

  const renameConversation = useCallback(async (conversationId: string, title: string) => {
    const summary = await renameConversationRequest(conversationId, { title });
    setHistoryMotionSource("user");
    syncSummary(summary);
    setConversationDetails((current) => {
      const detail = current[conversationId];
      if (!detail) {
        return current;
      }

      return {
        ...current,
        [conversationId]: {
          ...detail,
          title: summary.title,
          updated_at: summary.updated_at,
          last_message_preview: summary.last_message_preview,
          message_count: summary.message_count,
        },
      };
    });
  }, [syncSummary]);

  const toggleDesktopSidebar = useCallback(() => {
    setSidebarCollapsed((current) => !current);
  }, []);

  const closeMobileSidebar = useCallback(() => {
    setIsSidebarOpen(false);
  }, []);

  const openMobileSidebar = useCallback(() => {
    setIsSidebarOpen(true);
  }, []);

  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      try {
        await getHealth();
        if (cancelled) {
          return;
        }

        setHistoryMotionSource("system");
        const items = await listConversations();
        if (cancelled) {
          return;
        }

        setConversations(items);
        const firstId = items[0]?.id ?? null;
        setViewportMotionSource("system");
        setActiveConversationId(firstId);

        if (firstId) {
          await loadConversationDetail(firstId, { activate: true });
        }

        if (!cancelled) {
          setScreenError(null);
        }
      } catch (error) {
        if (cancelled) {
          return;
        }

        setScreenError({
          message:
            error instanceof ApiError
              ? error.status === 0
                ? "Cannot reach the backend."
                : error.detail
              : "Cannot reach the backend.",
        });
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
    };
  }, [loadConversationDetail]);

  return {
    conversations,
    conversationDetails,
    draftMessages,
    activeConversation,
    activeConversationId,
    activeConversationIdRef,
    loadingConversationId,
    deleteConfirmId,
    recentBornConversationId,
    screenError,
    isSidebarOpen,
    sidebarCollapsed,
    stickToBottom,
    viewportSceneKey,
    viewportMotionSource,
    historyMotionSource,
    isDraftSelected,
    currentMessages,
    activeTitle,
    conversationsRef,
    conversationDetailsRef,
    draftMessagesRef,
    setConversations,
    setConversationDetails,
    setDraftMessages,
    setActiveConversationId,
    setDeleteConfirmId,
    setScreenError,
    setStickToBottom,
    setLoadingConversationId,
    setViewportMotionSource,
    setHistoryMotionSource,
    syncSummary,
    syncConversation,
    patchConversationMessages,
    loadConversationDetail,
    refreshConversationList,
    reconcileConversation,
    selectConversation,
    openDraftConversation,
    markConversationBorn,
    restoreDraftMessages,
    restoreConversationSnapshot,
    clearDeleteConfirmation,
    deleteConversation,
    renameConversation,
    toggleDesktopSidebar,
    closeMobileSidebar,
    openMobileSidebar,
    prepareForNavigation,
  };
};

export type ConversationController = ReturnType<typeof useConversationController>;
