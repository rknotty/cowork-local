import { useEffect, useRef, useState } from "react";
import type { DragEvent, ReactElement, RefObject } from "react";
import { useFileUpload } from "../../hooks/use-file-upload";
import { useSession } from "../../state/session-context";
import { Composer } from "./composer";
import { Timeline } from "./timeline";

interface ConversationProps {
  orchestratorModelId: string | null;
}

const NEAR_BOTTOM_THRESHOLD_PX = 120;

/**
 * Keeps the newest content in view while the user is reading the end of the
 * conversation, and leaves the scroll position alone once they scroll up.
 */
function useStickToBottom(contentVersion: unknown): RefObject<HTMLDivElement | null> {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (scroller === null) {
      return undefined;
    }
    const handleScroll = (): void => {
      const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      isNearBottomRef.current = distance < NEAR_BOTTOM_THRESHOLD_PX;
    };
    scroller.addEventListener("scroll", handleScroll, { passive: true });
    return () => scroller.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (scroller !== null && isNearBottomRef.current) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  }, [contentVersion]);

  return scrollerRef;
}

const hasDraggedFiles = (event: DragEvent<HTMLElement>): boolean =>
  Array.from(event.dataTransfer.types).includes("Files");

/** The conversation column: a drop target, the timeline and the composer. */
export function Conversation({ orchestratorModelId }: ConversationProps): ReactElement {
  const { state } = useSession();
  const upload = useFileUpload();
  const [isDragTarget, setIsDragTarget] = useState(false);
  const scrollerRef = useStickToBottom(state.items);

  const handleDragOver = (event: DragEvent<HTMLElement>): void => {
    if (hasDraggedFiles(event)) {
      event.preventDefault();
      setIsDragTarget(true);
    }
  };
  const handleDrop = (event: DragEvent<HTMLElement>): void => {
    event.preventDefault();
    setIsDragTarget(false);
    void upload.uploadFiles(Array.from(event.dataTransfer.files));
  };

  return (
    <section
      className={isDragTarget ? "conversation is-drag-target" : "conversation"}
      aria-label="Conversation"
      onDragOver={handleDragOver}
      onDragLeave={() => setIsDragTarget(false)}
      onDrop={handleDrop}
    >
      {/* Focusable so keyboard users can scroll the conversation. */}
      <div
        className="conversation-scroller"
        ref={scrollerRef}
        role="region"
        aria-label="Messages"
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
      >
        <Timeline />
      </div>
      {isDragTarget && <p className="drop-hint">Drop files to add them to the session workspace</p>}
      <Composer upload={upload} orchestratorModelId={orchestratorModelId} />
    </section>
  );
}
