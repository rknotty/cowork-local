import { useRef } from "react";
import type { KeyboardEvent, ReactElement, ReactNode } from "react";

export interface TabDefinition<TabId extends string> {
  id: TabId;
  label: string;
}

interface TabsProps<TabId extends string> {
  /** Unique prefix for the tab and panel element IDs. */
  idPrefix: string;
  label: string;
  tabs: readonly TabDefinition<TabId>[];
  activeTabId: TabId;
  onSelect: (tabId: TabId) => void;
  children: ReactNode;
}

const NEXT_KEYS: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1 };

interface TabButtonProps {
  idPrefix: string;
  tabId: string;
  label: string;
  isActive: boolean;
  onSelect: () => void;
}

function TabButton({ idPrefix, tabId, label, isActive, onSelect }: TabButtonProps): ReactElement {
  return (
    <button
      id={`${idPrefix}-tab-${tabId}`}
      type="button"
      role="tab"
      className="tab"
      aria-selected={isActive}
      aria-controls={`${idPrefix}-panel`}
      // Roving tabindex: only the active tab is in the page's tab order.
      tabIndex={isActive ? 0 : -1}
      onClick={onSelect}
    >
      {label}
    </button>
  );
}

/**
 * An accessible tab set following the WAI-ARIA tabs pattern: one tab stop,
 * arrow keys move between tabs, and the panel is the next tab stop.
 */
export function Tabs<TabId extends string>(props: TabsProps<TabId>): ReactElement {
  const { idPrefix, label, tabs, activeTabId, onSelect, children } = props;
  const tabListRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    const step = NEXT_KEYS[event.key];
    if (step === undefined) {
      return;
    }
    event.preventDefault();
    const activeIndex = tabs.findIndex((tab) => tab.id === activeTabId);
    const nextTab = tabs[(activeIndex + step + tabs.length) % tabs.length];
    if (nextTab !== undefined) {
      onSelect(nextTab.id);
      tabListRef.current?.querySelector<HTMLElement>(`#${idPrefix}-tab-${nextTab.id}`)?.focus();
    }
  };

  return (
    <>
      {/* eslint-disable-next-line jsx-a11y/interactive-supports-focus */}
      <div
        className="tab-list"
        role="tablist"
        aria-label={label}
        ref={tabListRef}
        onKeyDown={handleKeyDown}
      >
        {tabs.map((tab) => (
          <TabButton
            key={tab.id}
            idPrefix={idPrefix}
            tabId={tab.id}
            label={tab.label}
            isActive={tab.id === activeTabId}
            onSelect={() => onSelect(tab.id)}
          />
        ))}
      </div>
      <div
        id={`${idPrefix}-panel`}
        className="tab-panel"
        role="tabpanel"
        aria-labelledby={`${idPrefix}-tab-${activeTabId}`}
      >
        {children}
      </div>
    </>
  );
}
