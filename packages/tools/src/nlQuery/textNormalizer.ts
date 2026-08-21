/**
 * 🌟 问句语气词、虚词预处理器 (Text Normalizer)
 * 职责：过滤无实体语义的客套词、语气助词、冗余引导语，避免污染指标与槽位识别
 */
export class TextNormalizer {
  private static readonly STOP_WORDS: RegExp[] = [
    /^(麻烦|请问|请|能否|帮我|麻烦帮我|请给我|给我|帮我看下|帮我查一下|查一下|看一下|查询|展示一下|给我展示一下|对比看看|看下|看看)\s*/gi,
    /(麻烦|请问|请|能否|帮我|给我展示一下|展示一下|查一下|看一下|看下|看看|里面|当中|之中)/gi,
  ];

  public static normalize(input: string): string {
    if (!input) return "";
    let text = input.trim();

    // 1. 过滤多余标点符号
    text = text.replace(/[？?！!，,。；;]/g, " ");

    // 2. 依次过滤虚词引导词与停用词
    for (const pattern of this.STOP_WORDS) {
      text = text.replace(pattern, " ");
    }

    // 3. 压缩多余空格
    return text.replace(/\s+/g, " ").trim();
  }
}
