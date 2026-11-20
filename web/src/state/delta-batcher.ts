import type { StreamEvent } from "../api/types";

export interface DeltaBatcher {
  /** Queues a text delta for the next frame, or emits any other event in order. */
  push: (event: StreamEvent) => void;
  /** Drops anything pending. Call when the stream is torn down. */
  cancel: () => void;
}

/**
 * Coalesces `text_delta` events into at most one emission per animation frame,
 * so a fast token stream costs one render per frame instead of one per token.
 * Non-text events flush pending text first, which keeps the original ordering.
 *
 * @param emit - Receives the merged text delta and every other event
 * @returns A batcher bound to `emit`
 */
export function createDeltaBatcher(emit: (event: StreamEvent) => void): DeltaBatcher {
  let pendingText = "";
  let frameHandle: number | null = null;

  const flush = (): void => {
    if (frameHandle !== null) {
      cancelAnimationFrame(frameHandle);
      frameHandle = null;
    }
    if (pendingText.length > 0) {
      const text = pendingText;
      pendingText = "";
      emit({ type: "text_delta", payload: { text } });
    }
  };

  const push = (event: StreamEvent): void => {
    if (event.type === "text_delta") {
      pendingText += event.payload.text;
      frameHandle ??= requestAnimationFrame(flush);
      return;
    }
    flush();
    emit(event);
  };

  const cancel = (): void => {
    if (frameHandle !== null) {
      cancelAnimationFrame(frameHandle);
      frameHandle = null;
    }
    pendingText = "";
  };

  return { push, cancel };
}
