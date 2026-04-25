export type Locale = "zh" | "en";

export const LOCALES: Locale[] = ["zh", "en"];

type Dictionary = {
  appTitle: string;
  appSubtitle: string;
  langToggle: string;
  download: string;
  printHint: string;
  chat: {
    tab: string;
    formTab: string;
    welcome: string;
    placeholder: string;
    send: string;
    sending: string;
    error: string;
    doneBanner: string;
  };
  sections: {
    agreement: string;
    parties: string;
    dates: string;
    governing: string;
    modifications: string;
  };
  labels: {
    purpose: string;
    purposeHelp: string;
    effectiveDate: string;
    mndaTerm: string;
    mndaTermExpires: string;
    mndaTermYears: string;
    mndaTermContinues: string;
    confidentialityTerm: string;
    confidentialityYears: string;
    confidentialityPerpetual: string;
    governingLaw: string;
    governingLawHelp: string;
    jurisdiction: string;
    jurisdictionHelp: string;
    modifications: string;
    modificationsHelp: string;
    party: string;
    party1: string;
    party2: string;
    company: string;
    signerName: string;
    signerTitle: string;
    noticeAddress: string;
    noticeAddressHelp: string;
  };
  placeholders: {
    purpose: string;
    governingLaw: string;
    jurisdiction: string;
    company: string;
    signerName: string;
    signerTitle: string;
    noticeAddress: string;
  };
};

const zh: Dictionary = {
  appTitle: "双方保密协议生成器",
  appSubtitle: "基于 Common Paper Mutual NDA v1.0。与 AI 对话生成协议，右侧实时预览，完成后点击下载 PDF。",
  langToggle: "English",
  download: "下载 PDF",
  printHint: "在打印对话框中选择「存储为 PDF / Save as PDF」。",
  chat: {
    tab: "AI 对话",
    formTab: "手动编辑",
    welcome:
      "你好！我来帮你起草一份双方保密协议。请告诉我，这份协议的目的是什么？(例如：评估合作机会、尽职调查)",
    placeholder: "输入消息……",
    send: "发送",
    sending: "正在发送…",
    error: "出错了，请重试。",
    doneBanner: "协议已就绪，可以在右侧预览并下载 PDF。",
  },
  sections: {
    agreement: "协议信息",
    parties: "双方信息",
    dates: "日期与期限",
    governing: "适用法律",
    modifications: "修订",
  },
  labels: {
    purpose: "目的",
    purposeHelp: "保密信息的使用目的",
    effectiveDate: "生效日期",
    mndaTerm: "协议期限",
    mndaTermExpires: "自生效日起满",
    mndaTermYears: "年后到期",
    mndaTermContinues: "持续有效，直至依约终止",
    confidentialityTerm: "保密期限",
    confidentialityYears: "年（自生效日起；商业秘密直至不再构成商业秘密为止）",
    confidentialityPerpetual: "永久",
    governingLaw: "适用法律",
    governingLawHelp: "美国州（例：Delaware）",
    jurisdiction: "管辖法院",
    jurisdictionHelp: "城市/县与州（例：courts located in New Castle, DE）",
    modifications: "对标准条款的修订",
    modificationsHelp: "留空表示不修改标准条款",
    party: "方",
    party1: "甲方",
    party2: "乙方",
    company: "公司名称",
    signerName: "签字人姓名",
    signerTitle: "签字人职务",
    noticeAddress: "通知地址",
    noticeAddressHelp: "邮箱或邮寄地址",
  },
  placeholders: {
    purpose: "Evaluating whether to enter into a business relationship with the other party.",
    governingLaw: "Delaware",
    jurisdiction: "courts located in New Castle, DE",
    company: "Acme, Inc.",
    signerName: "Jane Doe",
    signerTitle: "Chief Executive Officer",
    noticeAddress: "legal@acme.com",
  },
};

const en: Dictionary = {
  appTitle: "Mutual NDA Generator",
  appSubtitle: "Based on Common Paper Mutual NDA v1.0. Chat with the AI to draft, preview on the right, and download as PDF.",
  langToggle: "中文",
  download: "Download PDF",
  printHint: "In the print dialog, choose “Save as PDF” as the destination.",
  chat: {
    tab: "AI Chat",
    formTab: "Edit fields",
    welcome:
      "Hi! I'm here to help draft a Mutual NDA. To start: what's the purpose of this agreement? (e.g. evaluating a partnership, due diligence)",
    placeholder: "Type a message…",
    send: "Send",
    sending: "Sending…",
    error: "Something went wrong, please try again.",
    doneBanner: "Your MNDA is ready — review the preview and download the PDF.",
  },
  sections: {
    agreement: "Agreement",
    parties: "Parties",
    dates: "Dates & Term",
    governing: "Governing Law",
    modifications: "Modifications",
  },
  labels: {
    purpose: "Purpose",
    purposeHelp: "How Confidential Information may be used",
    effectiveDate: "Effective Date",
    mndaTerm: "MNDA Term",
    mndaTermExpires: "Expires",
    mndaTermYears: "year(s) from Effective Date",
    mndaTermContinues: "Continues until terminated in accordance with the MNDA",
    confidentialityTerm: "Term of Confidentiality",
    confidentialityYears: "year(s) from Effective Date; trade secrets until no longer trade secrets",
    confidentialityPerpetual: "In perpetuity",
    governingLaw: "Governing Law",
    governingLawHelp: "U.S. state (e.g., Delaware)",
    jurisdiction: "Jurisdiction",
    jurisdictionHelp: "City/county and state (e.g., courts located in New Castle, DE)",
    modifications: "Modifications to Standard Terms",
    modificationsHelp: "Leave blank for no modifications",
    party: "Party",
    party1: "Party 1",
    party2: "Party 2",
    company: "Company",
    signerName: "Print Name",
    signerTitle: "Title",
    noticeAddress: "Notice Address",
    noticeAddressHelp: "Email or postal address",
  },
  placeholders: {
    purpose: "Evaluating whether to enter into a business relationship with the other party.",
    governingLaw: "Delaware",
    jurisdiction: "courts located in New Castle, DE",
    company: "Acme, Inc.",
    signerName: "Jane Doe",
    signerTitle: "Chief Executive Officer",
    noticeAddress: "legal@acme.com",
  },
};

export const DICTIONARIES: Record<Locale, Dictionary> = { zh, en };

export function useDictionary(locale: Locale): Dictionary {
  return DICTIONARIES[locale];
}
