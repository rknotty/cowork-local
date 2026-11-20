import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Session } from "../../api/types";
import { SessionList } from "./session-list";

const SESSIONS: Session[] = [
  {
    session_id: "s1",
    title: "New session",
    workspace_path: "C:\\ws\\s1",
    created_at: "2026-11-19T10:00:00+00:00",
  },
  {
    session_id: "s2",
    title: "Budget review",
    workspace_path: "C:\\ws\\s2",
    created_at: "2026-11-18T10:00:00+00:00",
  },
];

describe("SessionList renaming", () => {
  const onRename = vi.fn();
  const onSelect = vi.fn();

  beforeEach(() => {
    onRename.mockReset();
    onSelect.mockReset();
  });

  const renderList = (): void => {
    render(
      <SessionList
        sessions={SESSIONS}
        activeSessionId="s1"
        onSelect={onSelect}
        onRename={onRename}
      />
    );
  };

  it("should save a new name on Enter, tidying its whitespace", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Rename New session" }));
    const field = screen.getByLabelText("Session name");
    await user.clear(field);
    await user.type(field, "  Partner   keynote  {Enter}");

    expect(onRename).toHaveBeenCalledExactlyOnceWith("s1", "Partner keynote");
    expect(screen.queryByLabelText("Session name")).not.toBeInTheDocument();
  });

  it("should cancel on Escape without saving", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Rename Budget review" }));
    await user.type(screen.getByLabelText("Session name"), " draft{Escape}");

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.getByText("Budget review")).toBeInTheDocument();
  });

  it("should not save a blank or unchanged name", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Rename Budget review" }));
    await user.keyboard("{Enter}");
    await user.click(screen.getByRole("button", { name: "Rename Budget review" }));
    await user.clear(screen.getByLabelText("Session name"));
    await user.keyboard("{Enter}");

    expect(onRename).not.toHaveBeenCalled();
  });

  it("should save when focus leaves the field", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Rename Budget review" }));
    await user.type(screen.getByLabelText("Session name"), " 2027");
    await user.tab();

    expect(onRename).toHaveBeenCalledExactlyOnceWith("s2", "Budget review 2027");
  });

  it("should still open a session when its title is clicked", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByText("Budget review"));

    expect(onSelect).toHaveBeenCalledWith("s2");
  });
});
