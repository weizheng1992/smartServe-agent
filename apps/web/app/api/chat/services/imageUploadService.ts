import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";

export interface ImageUploadResult {
  success: boolean;
  url?: string;
  filename?: string;
  originalName?: string;
  size?: number;
  mimeType?: string;
  error?: string;
  statusCode?: number;
}

export class ImageUploadService {
  public static readonly MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
  public static readonly ALLOWED_MIME_TYPES = new Set([
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
  ]);

  /**
   * 校验并安全持久化图片文件
   */
  public static async uploadImage(
    file: File | null,
  ): Promise<ImageUploadResult> {
    if (!file) {
      return {
        success: false,
        error: "No image file provided in form-data",
        statusCode: 400,
      };
    }

    if (!this.ALLOWED_MIME_TYPES.has(file.type)) {
      return {
        success: false,
        error: `Unsupported image format: ${file.type}. Allowed formats: JPG, PNG, WebP, GIF`,
        statusCode: 400,
      };
    }

    if (file.size > this.MAX_FILE_SIZE) {
      return {
        success: false,
        error: `File size exceeds 10MB limit (Current: ${(file.size / (1024 * 1024)).toFixed(2)}MB)`,
        statusCode: 413,
      };
    }

    const arrayBuffer = await file.arrayBuffer();
    const buffer = Buffer.from(arrayBuffer);

    // 计算哈希并确定文件后缀
    const hash = crypto
      .createHash("sha256")
      .update(buffer)
      .digest("hex")
      .slice(0, 12);
    const ext =
      file.name.split(".").pop()?.toLowerCase() ||
      (file.type === "image/png" ? "png" : "jpg");
    const uniqueFileName = `upload_${Date.now()}_${hash}.${ext}`;

    const uploadsDir = path.join(process.cwd(), "public", "uploads");
    if (!existsSync(uploadsDir)) {
      await mkdir(uploadsDir, { recursive: true });
    }

    const filePath = path.join(uploadsDir, uniqueFileName);
    await writeFile(filePath, buffer);

    const publicUrl = `/uploads/${uniqueFileName}`;

    return {
      success: true,
      url: publicUrl,
      filename: uniqueFileName,
      originalName: file.name,
      size: file.size,
      mimeType: file.type,
    };
  }
}
