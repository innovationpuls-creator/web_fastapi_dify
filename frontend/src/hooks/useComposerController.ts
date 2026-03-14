import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteUpload as deleteUploadRequest,
  uploadChatFile,
} from "../services/api";
import {
  cloneUpload,
  describeError,
  isRetryableError,
  resizeTextarea,
  type ComposerError,
  type PendingUpload,
} from "../features/chat/model";
import {
  createPendingUploads,
  patchUpload,
  removeUpload,
  validateUploadFiles,
} from "../features/chat/uploadHelpers";
import type { MotionSource } from "../motion/tokens";

export const useComposerController = () => {
  const [input, setInput] = useState("");
  const [pendingUploads, setPendingUploads] = useState<PendingUpload[]>([]);
  const [composerError, setComposerError] = useState<ComposerError | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [isInputFocused, setIsInputFocused] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [inputRippleKey, setInputRippleKey] = useState(0);
  const [motionSource, setMotionSource] = useState<MotionSource>("system");

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadControllersRef = useRef<Record<string, AbortController>>({});
  const pendingUploadsRef = useRef(pendingUploads);
  const dragDepthRef = useRef(0);

  useEffect(() => {
    pendingUploadsRef.current = pendingUploads;
  }, [pendingUploads]);

  useEffect(() => {
    resizeTextarea(textareaRef.current);
  }, [input]);

  const hasUploadingUploads = pendingUploads.some((upload) => upload.status === "uploading");
  const hasErroredUploads = pendingUploads.some((upload) => upload.status === "error");
  const isEditingMessage = editingMessageId !== null;

  const focusInput = useCallback(() => {
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      resizeTextarea(textareaRef.current);
    });
  }, []);

  const releaseUploads = useCallback((uploads: PendingUpload[], options: { deleteRemote: boolean }) => {
    uploads.forEach((upload) => {
      uploadControllersRef.current[upload.localId]?.abort();
      delete uploadControllersRef.current[upload.localId];

      if (options.deleteRemote && upload.uploadId) {
        void deleteUploadRequest(upload.uploadId).catch(() => undefined);
      }

      URL.revokeObjectURL(upload.previewUrl);
    });
  }, []);

  useEffect(
    () => () => {
      releaseUploads(pendingUploadsRef.current, { deleteRemote: true });
    },
    [releaseUploads],
  );

  const clearComposerError = useCallback(() => {
    setComposerError(null);
  }, []);

  const handleInputChange = useCallback((value: string) => {
    setMotionSource("user");
    setInput(value);
    setComposerError((current) => (current?.retryable ? null : current));
  }, []);

  const clearEditState = useCallback(() => {
    setEditingMessageId(null);
  }, []);

  const cancelEdit = useCallback(() => {
    setMotionSource("user");
    setEditingMessageId(null);
    setInput("");
  }, []);

  const beginEdit = useCallback((messageId: string, text: string) => {
    setMotionSource("user");
    releaseUploads(pendingUploadsRef.current, { deleteRemote: true });
    setPendingUploads([]);
    setComposerError(null);
    setEditingMessageId(messageId);
    setInput(text);
    setDragActive(false);
    dragDepthRef.current = 0;
    requestAnimationFrame(() => resizeTextarea(textareaRef.current));
  }, [releaseUploads]);

  const restoreEditState = useCallback((messageId: string, text: string) => {
    setMotionSource("system");
    setEditingMessageId(messageId);
    setInput(text);
    requestAnimationFrame(() => resizeTextarea(textareaRef.current));
  }, []);

  const resetComposer = useCallback(
    (options?: { deleteRemoteUploads?: boolean }) => {
      setMotionSource("system");
      releaseUploads(pendingUploadsRef.current, {
        deleteRemote: options?.deleteRemoteUploads ?? false,
      });
      setPendingUploads([]);
      setEditingMessageId(null);
      setInput("");
      setComposerError(null);
      setDragActive(false);
      dragDepthRef.current = 0;
      requestAnimationFrame(() => resizeTextarea(textareaRef.current));
    },
    [releaseUploads],
  );

  const restoreComposerSnapshot = useCallback((nextInput: string, uploads: PendingUpload[]) => {
    setMotionSource("system");
    setEditingMessageId(null);
    setInput(nextInput);
    setPendingUploads(uploads.map(cloneUpload));
    setDragActive(false);
    dragDepthRef.current = 0;
  }, []);

  const beginUpload = useCallback(async (upload: PendingUpload) => {
    const controller = new AbortController();
    uploadControllersRef.current[upload.localId] = controller;

    try {
      const response = await uploadChatFile(upload.file, controller.signal);
      setPendingUploads((current) =>
        patchUpload(current, upload.localId, (item) => ({
          ...item,
          uploadId: response.upload_id,
          status: "ready",
          error: null,
        })),
      );
      setComposerError((current) => (current?.retryable ? null : current));
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }

      const message = describeError(error, "Image upload failed.");
      setMotionSource("stream");
      setPendingUploads((current) =>
        patchUpload(current, upload.localId, (item) => ({
          ...item,
          status: "error",
          error: message,
        })),
      );
      setComposerError({
        message,
        retryable: isRetryableError(error),
      });
    } finally {
      delete uploadControllersRef.current[upload.localId];
    }
  }, []);

  const validateFiles = useCallback((files: File[]) => {
    const result = validateUploadFiles(pendingUploadsRef.current.length, files);
    if (!result.ok) {
      setMotionSource("user");
      setComposerError({
        message: result.message,
        retryable: false,
      });
      return false;
    }

    return true;
  }, []);

  const addFiles = useCallback(
    (files: File[], options?: { isBusy?: boolean }) => {
      if (options?.isBusy || files.length === 0) {
        return;
      }

      if (editingMessageId) {
        setMotionSource("user");
        setComposerError({
          message: "Images are unavailable while editing a message.",
          retryable: false,
        });
        return;
      }

      if (!validateFiles(files)) {
        return;
      }

      const nextUploads = createPendingUploads(files);

      setMotionSource("user");
      setComposerError(null);
      setPendingUploads((current) => [...current, ...nextUploads]);
      nextUploads.forEach((upload) => {
        void beginUpload(upload);
      });
    },
    [beginUpload, editingMessageId, validateFiles],
  );

  const retryUpload = useCallback(
    (localId: string) => {
      const target = pendingUploadsRef.current.find((upload) => upload.localId === localId);
      if (!target || target.status !== "error") {
        return;
      }

      const nextUpload: PendingUpload = {
        ...target,
        status: "uploading",
        error: null,
        uploadId: null,
      };

      setMotionSource("user");
      setComposerError(null);
      setPendingUploads((current) =>
        patchUpload(current, localId, () => nextUpload),
      );
      void beginUpload(nextUpload);
    },
    [beginUpload],
  );

  const removeUploadById = useCallback(
    async (localId: string) => {
      const target = pendingUploadsRef.current.find((upload) => upload.localId === localId);
      if (!target) {
        return;
      }

      uploadControllersRef.current[localId]?.abort();
      delete uploadControllersRef.current[localId];

      if (target.uploadId) {
        void deleteUploadRequest(target.uploadId).catch(() => undefined);
      }

      URL.revokeObjectURL(target.previewUrl);
      setMotionSource("user");
      setPendingUploads((current) => removeUpload(current, localId));
    },
    [],
  );

  const openFilePicker = useCallback(() => {
    setMotionSource("user");
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>, options?: { isBusy?: boolean }) => {
      const files = Array.from(event.target.files || []);
      addFiles(files, options);
      event.target.value = "";
    },
    [addFiles],
  );

  const handleComposerPaste = useCallback(
    (event: React.ClipboardEvent<HTMLTextAreaElement>, options?: { isBusy?: boolean }) => {
      const files = Array.from(event.clipboardData.files || []);
      if (files.length === 0) {
        return;
      }

      event.preventDefault();
      addFiles(files, options);
    },
    [addFiles],
  );

  const handleDragEnter = useCallback(
    (event: React.DragEvent<HTMLDivElement>, options?: { isBusy?: boolean }) => {
      if (options?.isBusy || !Array.from(event.dataTransfer.types).includes("Files")) {
        return;
      }

      event.preventDefault();
      dragDepthRef.current += 1;
      setMotionSource("user");
      setDragActive(true);
    },
    [],
  );

  const handleDragOver = useCallback(
    (event: React.DragEvent<HTMLDivElement>, options?: { isBusy?: boolean }) => {
      if (options?.isBusy || !Array.from(event.dataTransfer.types).includes("Files")) {
        return;
      }

      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    },
    [],
  );

  const handleDragLeave = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    if (!Array.from(event.dataTransfer.types).includes("Files")) {
      return;
    }

    event.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setMotionSource("user");
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>, options?: { isBusy?: boolean }) => {
      if (options?.isBusy || !Array.from(event.dataTransfer.types).includes("Files")) {
        return;
      }

      event.preventDefault();
      dragDepthRef.current = 0;
      setMotionSource("user");
      setDragActive(false);
      addFiles(Array.from(event.dataTransfer.files || []), options);
    },
    [addFiles],
  );

  return {
    input,
    pendingUploads,
    composerError,
    editingMessageId,
    isEditingMessage,
    isInputFocused,
    dragActive,
    inputRippleKey,
    motionSource,
    hasUploadingUploads,
    hasErroredUploads,
    textareaRef,
    fileInputRef,
    pendingUploadsRef,
    setInput,
    setPendingUploads,
    setComposerError,
    setIsInputFocused,
    setInputRippleKey,
    setMotionSource,
    focusInput,
    clearComposerError,
    clearEditState,
    cancelEdit,
    beginEdit,
    restoreEditState,
    handleInputChange,
    resetComposer,
    restoreComposerSnapshot,
    releaseUploads,
    addFiles,
    retryUpload,
    removeUpload: removeUploadById,
    openFilePicker,
    handleFileChange,
    handleComposerPaste,
    handleDragEnter,
    handleDragOver,
    handleDragLeave,
    handleDrop,
  };
};

export type ComposerController = ReturnType<typeof useComposerController>;
