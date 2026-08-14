export type Locale = "zh" | "en";

export const LOCALES: Locale[] = ["zh", "en"];

type Dictionary = {
  appTitle: string;
  appSubtitle: string;
  langToggle: string;
  download: string;
  downloadFormat: string;
  downloadFormatOptions: {
    docx: string;
    pdf: string;
  };
  downloadUnavailable: string;
  downloadIncomplete: string;
  downloadBlockedFields: string;
  downloadHint: string;
  previewToolbarHint: string;
  drafting: string;
  comingSoon: string;
  manifestNote: string;
  accountMenu: string;
  coverPage: {
    title: string;
    missing: string;
    otherTerms: string;
  };
  docForm: {
    required: string;
    confirm: string;
    reject: string;
    pending: string;
    confirmed: string;
    conflict: string;
    missing: string;
    current: string;
    candidate: string;
    emptyMissingConfirmDisabled: string;
  };
  templateUnavailable: string;
  pickDocPrompt: string;
  disclaimer: string;
  disclaimerShort: string;
  requiredProgress: string;
  signOut: string;
  auth: {
    welcome: string;
    pitch: string;
    signInTitle: string;
    registerTitle: string;
    email: string;
    password: string;
    passwordHelp: string;
    name: string;
    nameOptional: string;
    signInCta: string;
    registerCta: string;
    submitting: string;
    switchToRegister: string;
    switchToLogin: string;
    genericError: string;
  };
  sidebar: {
    title: string;
    newDraft: string;
    empty: string;
    untitled: string;
  };
  saveStatus: {
    saved: string;
    saving: string;
    failed: string;
    unsaved: string;
  };
  // Catalog id → display title for the active doc in the header and the
  // sidebar. Kept in lockstep with catalog.json by hand because the catalog
  // is small and the localized titles wouldn't survive a JSON-only sync.
  catalogTitles: Record<string, string>;
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
  appTitle: "法律协议生成器",
  appSubtitle: "中国法标准范本。与 AI 对话选择并起草协议，右侧实时预览。",
  langToggle: "English",
  download: "下载",
  downloadFormat: "下载格式",
  downloadFormatOptions: {
    docx: "DOCX · 可编辑",
    pdf: "PDF · 便于分发",
  },
  downloadUnavailable:
    "该文档尚无封面页字段清单，暂不支持下载，以免输出未填充的误导性文件。",
  downloadIncomplete:
    "封面页还有必填条款未填写，补齐后即可下载。可继续与 AI 对话或切换到手动编辑。",
  downloadBlockedFields: "请先确认这些必填字段：",
  downloadHint: "默认下载可编辑的 DOCX，也可切换为 PDF。",
  previewToolbarHint: "用对话或表单填写关键条款，必填齐全后可下载",
  drafting: "正在起草",
  comingSoon: "该文档的完整生成与 DOCX/PDF 下载即将上线。可继续与 AI 对话收集关键条款，下方为中国法范本预览。",
  manifestNote:
    "与 AI 对话或用手动编辑填写封面页关键条款；正文中高亮的术语引用封面页。必填项齐全后可下载 DOCX 或 PDF。",
  accountMenu: "账户菜单",
  coverPage: {
    title: "封面页",
    missing: "＿＿＿＿",
    otherTerms: "其他条款",
  },
  docForm: {
    required: "*必填",
    confirm: "确认",
    reject: "拒绝",
    pending: "待确认",
    confirmed: "已确认",
    conflict: "冲突",
    missing: "缺失",
    current: "当前",
    candidate: "候选",
    emptyMissingConfirmDisabled: "请先输入内容，再确认一个缺失字段。",
  },
  templateUnavailable: "模板未能加载，请稍后重试。",
  pickDocPrompt: "先与 AI 对话，告诉我你想要哪份协议。",
  disclaimer:
    "本文档为 AI 生成的草稿，仅供参考，不构成法律意见。正式签署前请交由执业律师审核。",
  disclaimerShort: "AI 草稿，不构成法律意见；正式签署前请执业律师审核。",
  requiredProgress: "必填",
  signOut: "退出登录",
  auth: {
    welcome: "Prelegal · 法律协议生成器",
    pitch:
      "与 AI 对话起草中国法标准协议范本。注册后即可保存草稿，随时回看与继续编辑。",
    signInTitle: "登录",
    registerTitle: "注册",
    email: "邮箱",
    password: "密码",
    passwordHelp: "至少 8 位",
    name: "姓名",
    nameOptional: "（可选）",
    signInCta: "登录",
    registerCta: "创建账号",
    submitting: "处理中…",
    switchToRegister: "还没有账号？立即注册",
    switchToLogin: "已有账号？登录",
    genericError: "请求失败，请稍后再试。",
  },
  sidebar: {
    title: "我的草稿",
    newDraft: "+ 新建协议",
    empty: "尚无草稿。开始一段对话即可自动保存。",
    untitled: "未命名草稿",
  },
  saveStatus: {
    saved: "已保存",
    saving: "正在保存…",
    failed: "保存失败",
    unsaved: "尚未保存",
  },
  catalogTitles: {
    "mutual-nda": "双方保密协议",
    "cloud-service-agreement": "SaaS 服务协议",
    "design-partner-agreement": "设计合作伙伴协议",
    "service-level-agreement": "服务等级协议（SLA）",
    "professional-services-agreement": "专业服务协议",
    "data-processing-agreement": "个人信息委托处理协议",
    "software-license-agreement": "软件许可协议",
    "partnership-agreement": "渠道合作协议",
    "pilot-agreement": "试点协议",
    "business-associate-agreement": "医疗健康数据合作协议",
    "ai-addendum": "人工智能服务附加条款",
  },
  chat: {
    tab: "AI 对话",
    formTab: "手动编辑",
    welcome:
      "你好！我来帮你起草一份法律协议。我们可以做哪一类？例如双方保密协议（MNDA）、云服务协议（CSA）、数据处理协议（DPA）等。",
    placeholder: "输入消息……",
    send: "发送",
    sending: "正在发送…",
    error: "出错了，请重试。",
    doneBanner: "协议已就绪，可以在右侧预览并下载 DOCX 或 PDF。",
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
    governingLawHelp: "默认：中华人民共和国法律",
    jurisdiction: "争议解决",
    jurisdictionHelp: "仲裁机构或管辖法院（例：上海仲裁委员会仲裁）",
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
    purpose: "评估双方之间的业务合作机会。",
    governingLaw: "中华人民共和国法律",
    jurisdiction: "上海仲裁委员会按其仲裁规则进行仲裁",
    company: "示例科技（北京）有限公司",
    signerName: "张三",
    signerTitle: "法定代表人",
    noticeAddress: "legal@example.com.cn",
  },
};

const en: Dictionary = {
  appTitle: "Legal Agreement Generator",
  appSubtitle: "PRC-law standard templates. Chat with the AI to pick and draft an agreement; preview on the right.",
  langToggle: "中文",
  download: "Download",
  downloadFormat: "Download format",
  downloadFormatOptions: {
    docx: "DOCX · editable",
    pdf: "PDF · easy to share",
  },
  downloadUnavailable:
    "Download is disabled for this document — it has no cover-page field manifest yet, so the output would be an unpopulated template.",
  downloadIncomplete:
    "Some required cover-page terms are still missing. Fill them in via chat or the edit tab to enable download.",
  downloadBlockedFields: "Confirm these required fields before downloading:",
  downloadHint: "Downloads an editable DOCX by default; PDF is also available.",
  previewToolbarHint:
    "Fill key terms via chat or form; download once required fields are complete.",
  drafting: "Drafting",
  comingSoon: "DOCX/PDF generation for this document is coming soon. The chat keeps collecting key terms; below is the underlying PRC-law template.",
  manifestNote:
    "Fill in the cover-page terms via chat or the edit tab; highlighted terms in the body reference the cover page. Download unlocks once all required terms are set.",
  accountMenu: "Account menu",
  coverPage: {
    title: "Cover Page",
    missing: "＿＿＿＿",
    otherTerms: "Other terms",
  },
  docForm: {
    required: "*required",
    confirm: "Confirm",
    reject: "Reject",
    pending: "Pending confirmation",
    confirmed: "Confirmed",
    conflict: "Conflict",
    missing: "Missing",
    current: "Current",
    candidate: "Candidate",
    emptyMissingConfirmDisabled: "Enter a value before confirming a missing field.",
  },
  templateUnavailable: "Couldn't load the template — please try again in a moment.",
  pickDocPrompt: "Start by telling the AI which agreement you'd like to draft.",
  disclaimer:
    "This document is an AI-generated draft for reference only and does not constitute legal advice. Have a licensed lawyer review it before formal execution.",
  disclaimerShort:
    "AI draft, not legal advice. Have a licensed lawyer review it before signing.",
  requiredProgress: "Required",
  signOut: "Sign out",
  auth: {
    welcome: "Prelegal · Legal Agreement Generator",
    pitch:
      "Chat with AI to draft PRC-law standard agreements. Sign up to save drafts and pick up where you left off.",
    signInTitle: "Sign in",
    registerTitle: "Create your account",
    email: "Email",
    password: "Password",
    passwordHelp: "8 characters minimum",
    name: "Name",
    nameOptional: "(optional)",
    signInCta: "Sign in",
    registerCta: "Create account",
    submitting: "…",
    switchToRegister: "Don't have an account? Register",
    switchToLogin: "Already have an account? Sign in",
    genericError: "Something went wrong. Please try again.",
  },
  sidebar: {
    title: "My drafts",
    newDraft: "+ New draft",
    empty: "No drafts yet — start a conversation and we'll save it automatically.",
    untitled: "Untitled draft",
  },
  saveStatus: {
    saved: "Saved",
    saving: "Saving…",
    failed: "Save failed",
    unsaved: "Unsaved",
  },
  catalogTitles: {
    "mutual-nda": "Mutual NDA (PRC law)",
    "cloud-service-agreement": "SaaS Service Agreement",
    "design-partner-agreement": "Design Partner Agreement",
    "service-level-agreement": "Service Level Agreement (SLA)",
    "professional-services-agreement": "Professional Services Agreement",
    "data-processing-agreement": "Personal Information Processing Agreement",
    "software-license-agreement": "Software License Agreement",
    "partnership-agreement": "Channel Partnership Agreement",
    "pilot-agreement": "Pilot Agreement",
    "business-associate-agreement": "Healthcare Data Cooperation Agreement",
    "ai-addendum": "AI Service Addendum",
  },
  chat: {
    tab: "AI Chat",
    formTab: "Edit fields",
    welcome:
      "Hi! I'm here to help draft a legal agreement. Which one — for example a Mutual NDA, Cloud Service Agreement, or Data Processing Agreement?",
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
    governingLawHelp: "Default: the laws of the People's Republic of China",
    jurisdiction: "Dispute Resolution",
    jurisdictionHelp: "Arbitration commission or competent court",
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
    purpose: "评估双方之间的业务合作机会。",
    governingLaw: "中华人民共和国法律",
    jurisdiction: "上海仲裁委员会按其仲裁规则进行仲裁",
    company: "示例科技（北京）有限公司",
    signerName: "张三",
    signerTitle: "法定代表人",
    noticeAddress: "legal@example.com.cn",
  },
};

export const DICTIONARIES: Record<Locale, Dictionary> = { zh, en };

export function useDictionary(locale: Locale): Dictionary {
  return DICTIONARIES[locale];
}
