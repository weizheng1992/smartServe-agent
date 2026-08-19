import { execSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import puppeteer, { type Browser } from "puppeteer-core";
import { z } from "zod";
import { registerTool } from "./registry";

// Helper to auto-detect installed Chrome executable path on current OS
function getLocalChromePath(): string {
  const platform = process.platform;
  if (platform === "darwin") {
    return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  }
  if (platform === "win32") {
    return "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
  }
  try {
    return execSync("which google-chrome").toString().trim();
  } catch {
    try {
      return execSync("which chromium-browser").toString().trim();
    } catch {
      return "/usr/bin/google-chrome";
    }
  }
}

export const takeScreenshot = {
  name: "takeScreenshot",
  description:
    "Takes a real physical screenshot of the specified webpage URL using local browser.",
  schema: z.object({
    url: z
      .string()
      .describe(
        "The URL of the webpage to capture, e.g. https://github.com or https://example.com",
      ),
    fullPage: z
      .boolean()
      .optional()
      .default(false)
      .describe("Whether to take a full page screenshot or just the viewport."),
  }),
  execute: async ({ url, fullPage }: { url: string; fullPage?: boolean }) => {
    const chromePath = getLocalChromePath();
    console.log(
      `[takeScreenshot] 🚀 正在直接调起您电脑本地的物理 Chrome 浏览器: ${chromePath}`,
    );

    // Create public screenshots directory inside apps/web/public so Next.js can serve it statically
    const publicScreenshotsDir = path.resolve(
      __dirname,
      "../../../../apps/web/public/screenshots",
    );
    try {
      if (!fs.existsSync(publicScreenshotsDir)) {
        fs.mkdirSync(publicScreenshotsDir, { recursive: true });
      }
    } catch (e) {
      console.warn(
        "[takeScreenshot] Failed to create physical folder, skipping...",
        e,
      );
    }

    const filename = `screenshot_${Date.now()}.png`;
    const physicalSavePath = path.join(publicScreenshotsDir, filename);
    const relativeUrlPath = `/screenshots/${filename}`;

    let browser: Browser | null = null;
    try {
      browser = await puppeteer.launch({
        executablePath: chromePath,
        headless: true,
        args: [
          "--no-sandbox",
          "--disable-setuid-sandbox",
          "--disable-gpu",
          "--disable-dev-shm-usage",
        ],
      });

      const page = await browser.newPage();
      await page.setViewport({ width: 1280, height: 800 });
      await page.setUserAgent(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      );

      console.log(`[takeScreenshot] 正在直接导航物理网页 URL: ${url}...`);
      await page.goto(url, { waitUntil: "networkidle2", timeout: 30000 });

      console.log(
        "[takeScreenshot] 物理导航成功，正在进行 100% 真实高清网页截图...",
      );

      // 100% Secure physical PNG file write to local file-system!
      await page.screenshot({
        path: physicalSavePath,
        type: "png",
        fullPage: fullPage,
      });

      console.log(
        `[takeScreenshot] ✅ 截图物理磁盘落盘成功: ${physicalSavePath}`,
      );
      await browser.close();

      return {
        success: true,
        url,
        timestamp: new Date().toISOString(),
        screenshotPath: relativeUrlPath, // 100% 纯物理静态文件相对路径（彻底告别超长 base64，保护 Temporal UI 绝对不崩溃！）
        message:
          "Physical screenshot captured successfully using your local Chrome browser!",
      };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      console.error(
        `❌ [takeScreenshot] 调用本地 Chrome 浏览器截图失败: ${errorMessage}`,
      );
      if (browser) {
        await browser.close();
      }

      return {
        success: false,
        error: `调用本地 Chrome 失败: ${errorMessage}. 请确保您的电脑上安装了 Chrome 浏览器，或使用真实的 URL 进行截图测试。`,
      };
    }
  },
};

registerTool(takeScreenshot);
