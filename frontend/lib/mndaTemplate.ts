// 《双方保密协议》标准条款 —— 中华人民共和国法律范本（Prelegal 范本 v1.0）。
//
// 由 AI 辅助起草的自研范本，术语体系遵循《民法典》合同编与
// 《反不正当竞争法》（商业秘密）。本范本不构成法律意见；
// 预览页与 PDF 均带有"签署前请由执业律师审核"的提示。
//
// {{placeholder}} 令牌与封面页字段一一对应，渲染时替换为用户填写的值。
// 键名保持既有 MndaState 的字段名（purpose/governingLaw/...），在中国法
// 语境下的语义为：governingLaw = 适用法律（默认"中华人民共和国法律"），
// jurisdiction = 争议解决方式（仲裁机构或管辖法院）。

export type PlaceholderKey =
  | "purpose"
  | "governingLaw"
  | "jurisdiction"
  | "effectiveDate"
  | "mndaTerm"
  | "confidentialityTerm";

export const STANDARD_TERMS_SECTIONS: { heading: string; body: string }[] = [
  {
    heading: "协议构成",
    body: "本《双方保密协议》由本标准条款及双方签署的封面页（以下合称\"**本协议**\"）构成。为{{purpose}}（以下简称\"**本目的**\"），任何一方（\"**披露方**\"）均可能向另一方（\"**接收方**\"）披露或提供：（一）披露方标明\"保密\"\"专有\"或类似字样的信息；或（二）根据信息性质及披露情形应被合理认为具有保密性质的信息（以下合称\"**保密信息**\"）。保密信息包括但不限于技术资料、经营信息、产品设计与规划、需求文档、价格、安全与合规文件、技术成果与专有技术，亦包括双方磋商的存在及进展情况和封面页所载信息。双方应填写并签署引用本标准条款的封面页（\"**封面页**\"）；封面页载明双方主体信息，本协议使用的名词以本标准条款或封面页的定义为准。",
  },
  {
    heading: "保密信息的使用与保护",
    body: "接收方应当：（一）仅为本目的使用保密信息；（二）未经披露方事先书面同意，不得向任何第三方披露保密信息，但接收方可以向其因本目的确有必要知悉的员工、代理人、顾问、承包商及其他代表披露，前提是该等人员受到不低于本协议标准的保密义务约束，且接收方对其遵守本协议的情况承担责任；（三）以不低于其保护自身同类信息的措施保护保密信息，且在任何情况下不得低于合理注意义务。",
  },
  {
    heading: "除外情形",
    body: "接收方能够举证证明下列情形之一的信息，不适用本协议项下的保密义务：（一）非因接收方过错已经公开或进入公有领域的；（二）接收方在披露方披露之前已经合法知悉且不负有保密义务的；（三）接收方从对该信息不负有保密义务的第三方合法获得的；（四）接收方未使用、未参考保密信息而独立开发取得的。",
  },
  {
    heading: "依法披露",
    body: "接收方根据法律、行政法规、监管机关要求或司法程序必须披露保密信息的，可以在必需的范围内予以披露，但应当在法律允许的范围内提前书面通知披露方，并在披露方承担费用的前提下，合理配合披露方就该等保密信息寻求保密处理或其他保护措施。",
  },
  {
    heading: "期限与终止",
    body: "本协议自{{effectiveDate}}起生效，有效期为{{mndaTerm}}。任何一方均可提前书面通知另一方终止本协议。无论本协议因何种原因期满或终止，接收方对保密信息承担的义务在{{confidentialityTerm}}内持续有效；对于构成商业秘密的保密信息，在其依法不再构成商业秘密之前，接收方应持续承担保密义务。",
  },
  {
    heading: "返还与销毁",
    body: "本协议期满、终止或经披露方随时书面要求时，接收方应当：（一）立即停止使用保密信息；（二）在收到披露方书面要求后及时销毁其占有或控制的全部保密信息或将其返还披露方；（三）经披露方要求，以书面形式确认其已履行前述义务。作为第（二）项的例外，接收方可以按照其正常执行的备份或档案留存制度或法律要求留存保密信息，但本协议条款对留存的保密信息继续适用。",
  },
  {
    heading: "权利保留",
    body: "披露方保留其对保密信息享有的全部知识产权及其他权利。披露方向接收方披露保密信息，不构成对任何知识产权或其他权利的许可、转让或授予。",
  },
  {
    heading: "不作保证",
    body: "所有保密信息均按\"现状\"提供。披露方不对保密信息的准确性、完整性、适用性或不侵犯第三方权利作出任何明示或默示的保证。",
  },
  {
    heading: "违约责任",
    body: "接收方违反本协议约定，给披露方造成损失的，应当赔偿披露方因此遭受的损失，包括披露方为调查违约行为、主张权利而支出的合理费用（含公证费、鉴定费及合理的律师费）。接收方的违约行为侵犯披露方商业秘密的，披露方还有权依照《中华人民共和国反不正当竞争法》等法律法规追究其法律责任。金钱赔偿不足以弥补损害的，披露方有权依法申请行为保全、禁令等救济措施。",
  },
  {
    heading: "适用法律与争议解决",
    body: "本协议的订立、效力、解释、履行及争议解决，均适用{{governingLaw}}（不含其冲突法规则）。因本协议引起的或与本协议有关的任何争议，双方应首先友好协商解决；自一方书面提出协商之日起三十（30）日内未能解决的，任何一方均有权提交{{jurisdiction}}。",
  },
  {
    heading: "其他约定",
    body: "本协议不构成任何一方向另一方披露保密信息或进行任何交易的义务。未经另一方事先书面同意，任何一方不得转让本协议项下的权利义务，但因合并、重组、收购或全部或实质全部资产转让而概括转让的除外；违反本条的转让行为无效。本协议对双方经许可的继受人具有约束力。任何弃权应由弃权方授权代表以书面形式作出，不得以行为推定。本协议任何条款被认定无效或不可执行的，不影响其余条款的效力。本协议（含封面页）构成双方就本协议标的达成的完整约定，并取代双方此前就该标的达成的全部口头或书面的谅解与约定。对本协议的任何变更、补充均应以双方签署的书面文件作出。与本协议有关的通知应以书面形式发送至封面页所载的电子邮箱或通讯地址，自送达时生效。本协议可以一式多份（含电子文本）签署，各份具有同等法律效力。",
  },
];

// 范本出处与许可说明 —— 渲染在预览页脚，替代原 Common Paper 归属声明。
export const TEMPLATE_VERSION_LABEL = "Prelegal 双方保密协议范本 v1.0";
export const TEMPLATE_NOTICE =
  "本范本由 AI 辅助起草，仅供参考，不构成法律意见；签署前请由执业律师审核。";

type Segment =
  | { type: "text"; value: string }
  | { type: "bold"; value: string }
  | { type: "placeholder"; key: PlaceholderKey };

const TOKEN_RE =
  /\*\*([^*]+)\*\*|{{(purpose|governingLaw|jurisdiction|effectiveDate|mndaTerm|confidentialityTerm)}}/g;

export function parseSegments(body: string): Segment[] {
  const segments: Segment[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  TOKEN_RE.lastIndex = 0;
  while ((match = TOKEN_RE.exec(body)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", value: body.slice(lastIndex, match.index) });
    }
    if (match[1] !== undefined) {
      segments.push({ type: "bold", value: match[1] });
    } else if (match[2] !== undefined) {
      segments.push({ type: "placeholder", key: match[2] as PlaceholderKey });
    }
    lastIndex = TOKEN_RE.lastIndex;
  }
  if (lastIndex < body.length) {
    segments.push({ type: "text", value: body.slice(lastIndex) });
  }
  return segments;
}
