/** Client-side upload checks (SRS UC-SCR-01 step 2.2 / alternate 3a; size limit ≤ 20 MB). */
import { strings } from '../strings';

export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/tiff'] as const;
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024; // SRS UC-SCR-01: ≤ 20 MB

/** Returns an error message, or `null` when the file can be screened (UC-SCR-01 alternate 3a). */
export function validateUpload(file: File | null): string | null {
  if (!file) return strings.uploadNoFile;
  if (!(ACCEPTED_TYPES as readonly string[]).includes(file.type)) return strings.uploadBadType;
  if (file.size > MAX_UPLOAD_BYTES) return strings.uploadTooLarge;
  return null;
}
