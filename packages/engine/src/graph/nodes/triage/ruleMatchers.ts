// 统一的失败/熔断/拒绝/取消状态正则校验模式
const FAILURE_RESPONSE_REGEX =
  /熔断|网络.*波动|资金.*保障|接口.*延迟|拒绝|驳回|取消|超时|rejected|cancelled|expired|failed|error/i;

const SYMBOL_ONLY_REGEX =
  /^[\s\d`~!@#$%^&*()_\-+=+\[\]{}|;:',.<>?/\\?？，。！；：‘“”、]+$/;

const HUMAN_ESCALATION_REGEX =
  /转人工|找客服|联系人工|人工客服|找人工|转接人工|转人工客服|human agent|talk to human|speak to agent|customer service representative/i;

const GREETING_REGEX =
  /^(你好|您好|哈喽|哈罗|hello|hi|hey|哈拉|早上好|下午好|晚上好)$/i;

const EXIT_REGEX = /^(再见|退出|bye|exit|quit|再见啦|拜拜|不聊了)$/i;

export class TriageRuleMatchers {
  static isFailedResponse(content: string): boolean {
    if (!content) return false;
    return FAILURE_RESPONSE_REGEX.test(content);
  }

  static isSymbolOnly(input: string): boolean {
    return SYMBOL_ONLY_REGEX.test(input);
  }

  static isHumanEscalationRequested(input: string): boolean {
    return HUMAN_ESCALATION_REGEX.test(input);
  }

  static isGreeting(cleanInput: string): boolean {
    return GREETING_REGEX.test(cleanInput);
  }

  static isExitCommand(cleanInput: string): boolean {
    return EXIT_REGEX.test(cleanInput);
  }
}
