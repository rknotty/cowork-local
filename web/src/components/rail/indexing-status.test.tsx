import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { FolderIndexStatus } from "../../api/types";
import { isAnyIndexing } from "../../hooks/use-indexing-status";
import { describeIndexing, IndexingStatusLine } from "./indexing-status";

const FOLDER = "C:\\Docs";

describe("describeIndexing", () => {
  it("should describe every state in plain English", () => {
    expect(describeIndexing({ folder: FOLDER, state: "not_indexed" })).toBe("Not indexed yet.");
    expect(describeIndexing({ folder: FOLDER, state: "scanning" })).toBe("Finding documents…");
    expect(
      describeIndexing({
        folder: FOLDER,
        state: "indexing",
        processed_file_count: 3,
        total_file_count: 10,
      })
    ).toBe("Indexing: 3 of 10 files.");
  });

  it("should count unchanged files as searchable and report skipped ones", () => {
    const done: FolderIndexStatus = {
      folder: FOLDER,
      state: "done",
      total_file_count: 10,
      indexed_file_count: 4,
      unchanged_file_count: 3,
      skipped_online_only_count: 2,
      failed_file_count: 1,
    };

    expect(describeIndexing(done)).toBe(
      "Searchable: 7 of 10 files. 2 online-only, not downloaded. 1 could not be read."
    );
  });

  it("should show the orchestrator's safe message when a run fails", () => {
    const failed: FolderIndexStatus = {
      folder: FOLDER,
      state: "failed",
      error_message: "The local model service is not available.",
    };

    expect(describeIndexing(failed)).toBe("The local model service is not available.");
  });
});

describe("IndexingStatusLine", () => {
  it("should show a progress bar while indexing", () => {
    render(
      <IndexingStatusLine
        status={{ folder: FOLDER, state: "indexing", processed_file_count: 2, total_file_count: 5 }}
      />
    );

    expect(screen.getByLabelText("Indexing progress")).toHaveAttribute("value", "2");
    expect(screen.getByRole("status")).toHaveTextContent("Indexing: 2 of 5 files.");
  });

  it("should list skipped files with their reasons", () => {
    render(
      <IndexingStatusLine
        status={{ folder: FOLDER, state: "done", failures: ["notes.docx: Invalid argument"] }}
      />
    );

    expect(screen.getByText("notes.docx: Invalid argument")).toBeInTheDocument();
  });

  it("should render nothing before the first status arrives", () => {
    const { container } = render(<IndexingStatusLine status={undefined} />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe("isAnyIndexing", () => {
  it("should be true only while a folder is scanning or indexing", () => {
    expect(isAnyIndexing([{ folder: FOLDER, state: "scanning" }])).toBe(true);
    expect(isAnyIndexing([{ folder: FOLDER, state: "done" }])).toBe(false);
    expect(isAnyIndexing([])).toBe(false);
  });
});
