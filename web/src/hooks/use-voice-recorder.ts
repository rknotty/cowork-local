import { useCallback, useEffect, useRef, useState } from "react";
import { postTranscription } from "../api/api-client";
import { ApiError } from "../api/api-error";
import { useAlerts } from "../state/alerts-context";

export type RecorderPhase = "idle" | "recording" | "transcribing";

export interface VoiceRecorder {
  phase: RecorderPhase;
  isSupported: boolean;
  /** Starts recording when idle, or stops and transcribes when recording. */
  toggleRecording: () => void;
}

const RECORDING_MIME_TYPE = "audio/webm";

const isRecordingSupported = (): boolean =>
  typeof MediaRecorder !== "undefined" &&
  typeof navigator.mediaDevices?.getUserMedia === "function" &&
  MediaRecorder.isTypeSupported(RECORDING_MIME_TYPE);

const microphoneError = (cause: unknown): ApiError =>
  new ApiError(
    "MICROPHONE_UNAVAILABLE",
    "The microphone could not be used. Check the browser's microphone permission.",
    "",
    0,
    cause
  );

const releaseMicrophone = (recorder: MediaRecorder): void => {
  recorder.stream.getTracks().forEach((track) => track.stop());
};

/** Opens the microphone and starts recording; `onStopped` receives the audio chunks. */
async function openRecorder(onStopped: (chunks: Blob[]) => void): Promise<MediaRecorder> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream, { mimeType: RECORDING_MIME_TYPE });
  const chunks: Blob[] = [];
  recorder.addEventListener("dataavailable", (event) => chunks.push(event.data));
  recorder.addEventListener("stop", () => {
    releaseMicrophone(recorder);
    onStopped(chunks);
  });
  recorder.start();
  return recorder;
}

/**
 * Records from the microphone and sends the audio for local transcription.
 * The text is handed to `onTranscribed` for the user to review; nothing is sent
 * to the agent from here.
 *
 * @param onTranscribed - Receives the transcribed text; must be stable
 * @returns The recorder phase, a support flag and a toggle
 */
export function useVoiceRecorder(onTranscribed: (text: string) => void): VoiceRecorder {
  const { reportError } = useAlerts();
  const [phase, setPhase] = useState<RecorderPhase>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);

  const transcribe = useCallback(
    async (chunks: Blob[]): Promise<void> => {
      setPhase("transcribing");
      try {
        const audio = new Blob(chunks, { type: RECORDING_MIME_TYPE });
        onTranscribed(await postTranscription(audio, RECORDING_MIME_TYPE));
      } catch (thrown) {
        reportError(thrown);
      } finally {
        setPhase("idle");
      }
    },
    [onTranscribed, reportError]
  );

  const startRecording = useCallback(async (): Promise<void> => {
    try {
      recorderRef.current = await openRecorder((chunks) => {
        recorderRef.current = null;
        void transcribe(chunks);
      });
      setPhase("recording");
    } catch (cause) {
      reportError(microphoneError(cause));
    }
  }, [transcribe, reportError]);

  const toggleRecording = useCallback((): void => {
    if (phase === "recording") {
      recorderRef.current?.stop();
    } else if (phase === "idle") {
      void startRecording();
    }
  }, [phase, startRecording]);

  useEffect(
    () => () => {
      // Leaving the page mid-recording must not keep the microphone open.
      if (recorderRef.current !== null) {
        releaseMicrophone(recorderRef.current);
      }
    },
    []
  );

  return { phase, isSupported: isRecordingSupported(), toggleRecording };
}
