export function decodeEscapedText(input: unknown): string {
  let text = String(input ?? "");
  if (!text) {
    return "";
  }

  if ((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'"))) {
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed === "string") {
        text = parsed;
      }
    } catch {
      // ignore
    }
  }

  for (let i = 0; i < 3; i += 1) {
    const next = text
      .replace(/\\\\u([0-9a-fA-F]{4})/g, "\\u$1")
      .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
      .replace(/\\n/g, "\n")
      .replace(/\\t/g, "\t");
    if (next === text) {
      break;
    }
    text = next;
  }

  return tryRepairMojibake(text);
}

function chineseCount(text: string): number {
  const matched = text.match(/[\u4e00-\u9fff]/g);
  return matched ? matched.length : 0;
}

function replacementCount(text: string): number {
  const matched = text.match(/[\uFFFD?]/g);
  return matched ? matched.length : 0;
}

function tryLatin1ToUtf8(text: string): string {
  try {
    if (typeof TextDecoder === "undefined") {
      return text;
    }
    const bytes = Uint8Array.from(Array.from(text).map((ch) => ch.charCodeAt(0) & 0xff));
    return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
  } catch {
    return text;
  }
}

function tryRepairMojibake(text: string): string {
  const candidates: string[] = [text];

  const latin1Candidate = tryLatin1ToUtf8(text);
  if (latin1Candidate && latin1Candidate !== text) {
    candidates.push(latin1Candidate);
  }

  try {
    // eslint-disable-next-line deprecation/deprecation
    const uriCandidate = decodeURIComponent(escape(text));
    if (uriCandidate && uriCandidate !== text) {
      candidates.push(uriCandidate);
    }
  } catch {
    // ignore
  }

  let best = text;
  let bestScore = chineseCount(text) * 3 - replacementCount(text);
  candidates.forEach((item) => {
    const score = chineseCount(item) * 3 - replacementCount(item);
    if (score > bestScore) {
      best = item;
      bestScore = score;
    }
  });
  return best;
}

function simplifyForNurse(text: string): string {
  return text
    .replace(/AI Agent集群/g, "系统协同")
    .replace(/AI Agent/g, "系统")
    .replace(/Planner Agent/g, "顺序整理")
    .replace(/Memory Agent/g, "历史回看")
    .replace(/Patient Context Agent/g, "患者背景整理")
    .replace(/Order Signal Agent/g, "医嘱核对")
    .replace(/Recommendation Agent/g, "处理建议")
    .replace(/Collaboration Agent/g, "医生沟通")
    .replace(/Handover Agent/g, "交班整理")
    .replace(/Document Agent/g, "记录整理")
    .replace(/Action Agent/g, "结果汇总")
    .replace(/自动闭环已完成初步分析/g, "系统已经先帮你完成一轮梳理")
    .replace(/已完成自动闭环预演/g, "系统已先走完一轮预演")
    .replace(/自治闭环/g, "持续跟进")
    .replace(/自动闭环/g, "持续跟进")
    .replace(/当前回复整理/g, "基础整理")
    .replace(/下一步安排/g, "下一步提醒")
    .replace(/重点再看一遍/g, "重点复看")
    .replace(/附件读取/g, "附件查看")
    .replace(/当前重点[:：]/g, "现在先关注：")
    .replace(/建议动作[:：]/g, "建议先做：")
    .replace(/等待人工审批[:：]/g, "待你确认：")
    .replace(/仍需护士人工确认后继续。?/g, "下面涉及联系医生、交班或文书的动作，需要你确认后系统才会继续。")
    .replace(/审批闸门/g, "确认步骤")
    .replace(/人工闸门/g, "人工确认")
    .replace(/人工复核/g, "人工确认")
    .replace(/已闭环/g, "已完成")
    .replace(/未闭环/g, "待继续处理")
    .replace(/结构化建议/g, "可执行建议")
    .replace(/病例信息整理/g, "患者背景整理")
    .replace(/病例上下文/g, "患者背景")
    .replace(/风险标签/g, "风险提醒")
    .replace(/写入审计日志/g, "保存处理记录")
    .replace(/执行回收/g, "结果回收")
    .replace(/run\b/gi, "本次处理");
}

export function formatAiText(input: unknown): string {
  let text = decodeEscapedText(input);
  if (!text) {
    return "";
  }

  text = text
    .replace(/\r\n/g, "\n")
    .replace(/\u0000/g, "")
    .replace(/```[a-zA-Z]*\n?/g, "")
    .replace(/```/g, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/\t/g, "  ");

  const cleaned: string[] = [];
  text.split("\n").forEach((raw) => {
    let line = raw.trim();
    if (!line) {
      cleaned.push("");
      return;
    }

    line = line.replace(/^#{1,6}\s*/g, "");
    if (/^\|?[\s:-]+\|[\s|:-]*$/.test(line)) {
      return;
    }

    if (line.startsWith("|") && line.endsWith("|")) {
      const cells = line
        .slice(1, -1)
        .split("|")
        .map((x) => x.trim())
        .filter(Boolean);
      if (cells.length === 2) {
        line = `${cells[0]}：${cells[1]}`;
      } else if (cells.length > 2) {
        line = `• ${cells.join(" / ")}`;
      }
    }

    line = line.replace(/^\s*[-*+]\s+/, "• ");
    line = line.replace(/^\s*(\d+)\.\s+/, "$1. ");
    line = line.replace(/\*(.*?)\*/g, "$1");
    line = line.replace(/~~(.*?)~~/g, "$1");
    line = line.replace(/\s{2,}/g, " ").trim();

    cleaned.push(line);
  });

  return simplifyForNurse(cleaned.join("\n").replace(/\n{3,}/g, "\n\n").trim());
}
