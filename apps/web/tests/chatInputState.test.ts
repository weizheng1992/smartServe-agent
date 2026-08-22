import { describe, expect, it } from "bun:test";

describe("Chat Input State Management & Clear Verification", () => {
  it("should guarantee input is cleared upon submission", () => {
    let inputState = "帮我查询订单 ORD-98712";
    let attachedImages = ["https://cdn.example.com/receipt.png"];

    // Simulation of onSubmit handler
    const onSubmit = (
      input: string,
      images: string[],
      setInput: (val: string) => void,
      setImages: (imgs: string[]) => void,
      handleSend: (text: string, imgs: string[]) => void,
    ) => {
      if (!input.trim() && images.length === 0) return;
      const currentInput = input;
      const currentImages = [...images];
      setInput("");
      setImages([]);
      handleSend(currentInput, currentImages);
    };

    let sentText = "";
    let sentImages: string[] = [];

    onSubmit(
      inputState,
      attachedImages,
      (val) => {
        inputState = val;
      },
      (imgs) => {
        attachedImages = imgs;
      },
      (text, imgs) => {
        sentText = text;
        sentImages = imgs;
      },
    );

    // Assert that the dispatched message contains the original text and images
    expect(sentText).toBe("帮我查询订单 ORD-98712");
    expect(sentImages).toEqual(["https://cdn.example.com/receipt.png"]);

    // Assert that the input box state and attached images are immediately emptied
    expect(inputState).toBe("");
    expect(attachedImages.length).toBe(0);
  });

  it("should clear pending loader when human support is active", () => {
    interface Message {
      id: string;
      role: string;
      content: string;
      isLoading?: boolean;
      jobId?: string;
    }

    let messages: Message[] = [
      { id: "1", role: "user", content: "转人工" },
      { id: "2", role: "assistant", content: "已为您接通人工客服" },
      { id: "3", role: "user", content: "没有" },
      {
        id: "opt_loader",
        role: "assistant",
        content: "",
        isLoading: true,
        jobId: "pending-job",
      },
    ];

    // Simulated isHumanActive callback behavior
    const handleHumanActive = (
      setMessages: (updater: (prev: Message[]) => Message[]) => void,
    ) => {
      // 1. Remove pending loader
      setMessages((prev) =>
        prev.filter((m) => !m.isLoading && m.jobId !== "pending-job"),
      );
    };

    handleHumanActive((updater) => {
      messages = updater(messages);
    });

    // Ensure no pending loader remains in the list
    expect(messages.some((m) => m.isLoading || m.jobId === "pending-job")).toBe(
      false,
    );
    expect(messages.length).toBe(3);
    expect(messages[2].content).toBe("没有");
  });
});
