import type { DamageAssessmentData } from "types";
import { getLLM } from "../llm/callLLMWithRetry";

export interface VisionAnalysisResult {
  visualSummary: string;
  detectedObjects: string[];
  extractedOrderId?: string;
  extractedTrackingNumber?: string;
  damageAssessment?: DamageAssessmentData;
  ocrText?: string;
}

// 🛡️ PII 敏感信息掩码过滤
function scrubSensitiveInfo(text: string): string {
  if (!text) return text;
  return text
    .replace(
      /(?:\+?86)?1[3-9]\d{9}/g,
      (m) => `${m.substring(0, 3)}****${m.substring(7)}`,
    ) // 手机号
    .replace(
      /\b\d{6}(18|19|20)?\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b/g,
      "[ID_CARD_REDACTED]",
    ) // 身份证
    .replace(/\b(?:\d{4}[ -]?){3}\d{4}\b/g, "[BANK_CARD_REDACTED]"); // 银行卡
}

/**
 * 提取并构建启发式破损定责评估对象 (Unified Heuristic Assessment Helper)
 */
function buildHeuristicDamageAssessment(
  combinedQuery: string,
  primaryUrl: string,
): DamageAssessmentData | undefined {
  const isDamage =
    /破损|坏了|碎了|裂开|漏液|划痕|撕裂|瑕疵|damage|broken|crack|stain|defect/i.test(
      combinedQuery,
    );
  if (!isDamage) return undefined;

  const isSevere = /严重|彻底|全碎|碎裂|severe|crushed/i.test(combinedQuery);
  return {
    damageLevel: isSevere ? "severe" : "minor",
    summary: isSevere
      ? "用户上传了商品严重破损/碎裂照片"
      : "用户上传了商品瑕疵/局部破损凭证照片",
    confidence: 0.88,
    suggestedAction: isSevere ? "auto_refund" : "human_review",
    imageUrl: primaryUrl,
  };
}

export class VisionAnalyzerService {
  /**
   * 视觉与多模态核心解析：提取破损定责评估、OCR面单文本与订单运单实体
   */
  static async analyzeImages(
    imageUrls: string[],
    userPrompt = "",
    jobId?: string,
  ): Promise<VisionAnalysisResult> {
    if (!imageUrls || imageUrls.length === 0) {
      return {
        visualSummary: "",
        detectedObjects: [],
      };
    }

    const primaryUrl = imageUrls[0];

    // 1. 规则与关键词前置极速感知 (Fast Heuristic Path)
    const rawText = `${userPrompt} ${imageUrls.join(" ")}`;
    const combinedQuery = rawText.toLowerCase();
    const orderMatch = rawText
      .match(/\bORD-[A-Za-z0-9]+\b/i)?.[0]
      ?.toUpperCase();
    const trackingMatch = rawText
      .match(/\b(SF|YTO|ZTO|EMS|TRACK)[\d\w]{8,14}\b/i)?.[0]
      ?.toUpperCase();

    // 2. 多模态大模型视觉精判
    try {
      const llm = getLLM(jobId);
      const prompt = `You are an expert AI Vision and OCR inspection assistant for an e-commerce customer support platform.
Analyze the provided image(s) and user message.
User Message: "${userPrompt}"
Image URLs: ${imageUrls.join(", ")}

Your tasks:
1. OCR: Extract any visible Order IDs (e.g. "ORD-12345"), Tracking/Airway Bill Numbers (e.g. "SF1234567890"), and general text.
2. Defect & Damage Inspection: Determine if the product has damage or defects.
   - damageLevel: "negligible" (minor scratch/normal wear), "minor" (small defect/stain), or "severe" (shattered/crushed/completely unusable).
   - summary: Brief Chinese description of the damage or visual content.
   - suggestedAction: "auto_refund" | "require_inspection" | "human_review".
3. Return a JSON object with keys:
   - "visualSummary": string
   - "detectedObjects": string[]
   - "extractedOrderId": string or null
   - "extractedTrackingNumber": string or null
   - "ocrText": string or null
   - "damageAssessment": { "damageLevel": "negligible"|"minor"|"severe", "summary": string, "confidence": number, "suggestedAction": "auto_refund"|"require_inspection"|"human_review" } or null

Return ONLY valid raw JSON without markdown markers.`;

      // 构造 LangChain 多模态 HumanMessage 格式
      const messageContent: Array<
        | { type: "text"; text: string }
        | { type: "image_url"; image_url: { url: string } }
      > = [{ type: "text", text: prompt }];

      for (const url of imageUrls) {
        messageContent.push({
          type: "image_url",
          image_url: { url },
        });
      }

      const humanMsg = { role: "user", content: messageContent };
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error("LLM vision timeout")), 1500),
      );
      const response = await Promise.race([
        llm.invoke([humanMsg]),
        timeoutPromise,
      ]);
      const content =
        typeof response === "string"
          ? response
          : (response as { content?: string }).content || "";

      const cleanJson = content
        .trim()
        .replace(/^```json\s*/, "")
        .replace(/```$/, "")
        .trim();

      const parsed = JSON.parse(cleanJson);

      const damageAssessment: DamageAssessmentData | undefined =
        parsed.damageAssessment
          ? {
              damageLevel: parsed.damageAssessment.damageLevel || "minor",
              summary: scrubSensitiveInfo(
                parsed.damageAssessment.summary || "商品外观检测",
              ),
              confidence: parsed.damageAssessment.confidence || 0.85,
              suggestedAction:
                parsed.damageAssessment.suggestedAction || "human_review",
              imageUrl: primaryUrl,
            }
          : buildHeuristicDamageAssessment(combinedQuery, primaryUrl);

      return {
        visualSummary: scrubSensitiveInfo(parsed.visualSummary || ""),
        detectedObjects: parsed.detectedObjects || [],
        extractedOrderId: parsed.extractedOrderId || orderMatch,
        extractedTrackingNumber:
          parsed.extractedTrackingNumber || trackingMatch,
        ocrText: scrubSensitiveInfo(parsed.ocrText || ""),
        damageAssessment,
      };
    } catch (visionErr) {
      console.warn(
        "[VisionAnalyzerService] Multimodal LLM inspection fallback to heuristics:",
        visionErr,
      );

      // 降级兜底：基于统一启发式规则返回结构化视觉分析
      const damageAssessment = buildHeuristicDamageAssessment(
        combinedQuery,
        primaryUrl,
      );

      return {
        visualSummary: "已接收并解析用户上传的商品与物流凭证图片",
        detectedObjects: ["product_image", "receipt"],
        extractedOrderId: orderMatch,
        extractedTrackingNumber: trackingMatch,
        ocrText: orderMatch || trackingMatch || "",
        damageAssessment,
      };
    }
  }
}
