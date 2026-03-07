import {
  ALLOWED_UPLOAD_TYPES,
  MAX_UPLOAD_BYTES,
  MAX_UPLOAD_COUNT,
  createLocalId,
  type PendingUpload,
} from "./model";

export type UploadValidationResult =
  | { ok: true }
  | { ok: false; message: string };

export const validateUploadFiles = (
  currentCount: number,
  files: File[],
): UploadValidationResult => {
  if (currentCount + files.length > MAX_UPLOAD_COUNT) {
    return {
      ok: false,
      message: `Attach up to ${MAX_UPLOAD_COUNT} images.`,
    };
  }

  for (const file of files) {
    if (!ALLOWED_UPLOAD_TYPES.has(file.type)) {
      return {
        ok: false,
        message: "Only PNG, JPEG, and WEBP images are supported.",
      };
    }

    if (file.size > MAX_UPLOAD_BYTES) {
      return {
        ok: false,
        message: `Image exceeds ${Math.floor(MAX_UPLOAD_BYTES / 1_000_000)} MB.`,
      };
    }
  }

  return { ok: true };
};

export const createPendingUploads = (files: File[]): PendingUpload[] =>
  files.map((file) => ({
    localId: createLocalId("upload"),
    file,
    previewUrl: URL.createObjectURL(file),
    uploadId: null,
    status: "uploading",
    mediaType: file.type,
    byteSize: file.size,
  }));

export const patchUpload = (
  uploads: PendingUpload[],
  localId: string,
  updater: (upload: PendingUpload) => PendingUpload,
) => uploads.map((upload) => (upload.localId === localId ? updater(upload) : upload));

export const removeUpload = (uploads: PendingUpload[], localId: string) =>
  uploads.filter((upload) => upload.localId !== localId);
