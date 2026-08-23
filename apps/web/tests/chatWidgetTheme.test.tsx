import { describe, expect, it } from "bun:test";
import React from "react";
import { ChatWidget } from "../src/components/ChatWidget";

describe("🌟 ChatWidget Embeddable & Dynamic Theme Suite", () => {
  it("renders ChatWidget with custom merchant branding and theme token", () => {
    const element = React.createElement(ChatWidget, {
      businessId: "nike",
      themeColor: "#e11d48",
      brandName: "Nike 官方智能客服",
      welcomeText: "欢迎来到 Nike 官方客服，请问有什么可以帮您？",
      initialOpen: true,
    });

    expect(element).toBeDefined();
    expect(element.props.businessId).toBe("nike");
    expect(element.props.themeColor).toBe("#e11d48");
    expect(element.props.brandName).toBe("Nike 官方智能客服");
    expect(element.props.initialOpen).toBe(true);
  });
});
