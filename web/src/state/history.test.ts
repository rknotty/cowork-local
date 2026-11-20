import { describe, expect, it } from "vitest";
import type { Message } from "../api/types";
import { messagesToDrafts } from "./history";

describe("messagesToDrafts", () => {
  it("should return no items when there are no messages", () => {
    expect(messagesToDrafts([])).toEqual([]);
  });

  it("should fold a tool message into the card of the call it answers", () => {
    const messages: Message[] = [
      { role: "user", content: "Read it", model_id: "" },
      {
        role: "assistant",
        content: "",
        model_id: "example-model-14b:2",
        tool_calls: [
          { id: "call-1", function: { name: "read_file", arguments: '{"path":"a.txt"}' } },
        ],
      },
      { role: "tool", content: "file body", model_id: "", tool_call_id: "call-1" },
      { role: "assistant", content: "Done.", model_id: "example-model-14b:2" },
    ];

    const drafts = messagesToDrafts(messages);

    expect(drafts.map((draft) => draft.kind)).toEqual([
      "user_message",
      "tool_call",
      "assistant_text",
    ]);
    expect(drafts[1]).toMatchObject({
      toolName: "read_file",
      arguments: { path: "a.txt" },
      resultPreview: "file body",
      status: "recorded",
    });
    expect(drafts[2]).toMatchObject({ text: "Done.", modelId: "example-model-14b:2" });
  });

  it("should keep unparseable tool arguments as raw text", () => {
    const messages: Message[] = [
      {
        role: "assistant",
        content: "",
        model_id: "m:1",
        tool_calls: [{ id: "call-1", function: { name: "run", arguments: "not json" } }],
      },
    ];

    expect(messagesToDrafts(messages)[0]).toMatchObject({ arguments: { raw: "not json" } });
  });
});
