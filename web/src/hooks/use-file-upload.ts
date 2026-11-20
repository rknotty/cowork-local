import { useCallback, useState } from "react";
import { putFile } from "../api/api-client";
import { useAlerts } from "../state/alerts-context";
import { useSession } from "../state/session-context";

export interface FileUpload {
  isUploading: boolean;
  /** Names uploaded since the session opened, newest last. */
  uploadedNames: string[];
  uploadFiles: (files: File[]) => Promise<void>;
}

/**
 * Uploads files into the active session's workspace, one at a time so a failure
 * names a single file and the earlier ones are still kept.
 *
 * @returns Upload state and the upload function
 */
export function useFileUpload(): FileUpload {
  const { sessionId, dispatch } = useSession();
  const { reportError } = useAlerts();
  const [isUploading, setIsUploading] = useState(false);
  const [uploadedNames, setUploadedNames] = useState<string[]>([]);

  const uploadFiles = useCallback(
    async (files: File[]): Promise<void> => {
      if (files.length === 0) {
        return;
      }
      setIsUploading(true);
      try {
        for (const file of files) {
          await putFile(sessionId, file.name, file);
          setUploadedNames((names) => [...names, file.name]);
        }
      } catch (thrown) {
        reportError(thrown);
      } finally {
        setIsUploading(false);
        dispatch({ type: "workspace_changed" });
      }
    },
    [sessionId, dispatch, reportError]
  );

  return { isUploading, uploadedNames, uploadFiles };
}
