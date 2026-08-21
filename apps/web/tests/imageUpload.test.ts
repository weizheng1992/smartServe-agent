import { describe, expect, it } from "bun:test";
import { POST } from "../app/api/chat/upload/route";
import { NextRequest } from "next/server";

describe("📸 Image Upload API Endpoint", () => {
  it("应拒绝没有文件的空请求", async () => {
    const formData = new FormData();
    const req = new NextRequest("http://localhost:3000/api/chat/upload", {
      method: "POST",
      body: formData,
    });

    const res = await POST(req);
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(json.success).toBe(false);
    expect(json.error).toContain("No image file provided");
  });

  it("应拒绝不受支持的文件格式 (如 text/plain)", async () => {
    const formData = new FormData();
    const fakeFile = new File(["fake text content"], "test.txt", {
      type: "text/plain",
    });
    formData.append("file", fakeFile);

    const req = new NextRequest("http://localhost:3000/api/chat/upload", {
      method: "POST",
      body: formData,
    });

    const res = await POST(req);
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(json.success).toBe(false);
    expect(json.error).toContain("Unsupported image format");
  });

  it("应正常保存合规的 PNG/JPG 图片并返回访问 URL", async () => {
    const formData = new FormData();
    const fakeImage = new File(
      [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])],
      "broken_shoe.png",
      {
        type: "image/png",
      },
    );
    formData.append("file", fakeImage);

    const req = new NextRequest("http://localhost:3000/api/chat/upload", {
      method: "POST",
      body: formData,
    });

    const res = await POST(req);
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
    expect(json.url).toMatch(/^\/uploads\/upload_\d+_[a-f0-9]+\.png$/);
    expect(json.filename).toContain(".png");
  });

  it("应正常支持并保存 GIF 图片", async () => {
    const formData = new FormData();
    const fakeGif = new File(
      [new Uint8Array([71, 73, 70, 56, 57, 97])],
      "damage_anim.gif",
      {
        type: "image/gif",
      },
    );
    formData.append("file", fakeGif);

    const req = new NextRequest("http://localhost:3000/api/chat/upload", {
      method: "POST",
      body: formData,
    });

    const res = await POST(req);
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
    expect(json.url).toMatch(/^\/uploads\/upload_\d+_[a-f0-9]+\.gif$/);
    expect(json.filename).toContain(".gif");
  });
});
