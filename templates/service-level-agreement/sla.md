# 服务等级协议（SLA）

1. <span class="header_2" id="1">总则</span>
    1. <span class="header_3" id="1.1">附件地位。</span>  本服务等级协议（以下简称"本协议"）是<span class="coverpage_link">服务方</span>与<span class="coverpage_link">客户</span>之间<span class="keyterms_link">主协议</span>的组成附件，用于约定<span class="coverpage_link">服务方</span>就云服务（以下简称"服务"）向<span class="coverpage_link">客户</span>作出的可用性承诺、故障响应义务以及未达标时的服务积分补偿。本协议未约定的事项，适用<span class="keyterms_link">主协议</span>的约定；本协议与<span class="keyterms_link">主协议</span>不一致的，就服务等级事项以本协议为准。
    2. <span class="header_3" id="1.2">生效与适用。</span>  本协议自<span class="keyterms_link">生效日期</span>起生效，在<span class="keyterms_link">主协议</span>项下服务的订购期限内持续适用；<span class="keyterms_link">主协议</span>终止的，本协议同时终止。
    3. <span class="header_3" id="1.3">承诺性质。</span>  本协议项下的可用率承诺与响应时限承诺，仅适用于<span class="coverpage_link">客户</span>已付费订购的正式生产环境服务，不适用于免费、试用、测试或预览版本的服务。

2. <span class="header_2" id="2">服务可用性承诺</span>
    1. <span class="header_3" id="2.1">可用率目标。</span>  在每个<span class="orderform_link">统计周期</span>内，<span class="coverpage_link">服务方</span>承诺服务可用率不低于<span class="orderform_link">可用率目标</span>。
    2. <span class="header_3" id="2.2">可用率计算。</span>  服务可用率 =（<span class="orderform_link">统计周期</span>内总分钟数 − 不可用分钟数）÷ <span class="orderform_link">统计周期</span>内总分钟数 × 100%。"不可用分钟数"指服务整体不能被正常访问或者核心功能不能正常使用、且持续五（5）分钟以上的累计分钟数；持续时间不足五（5）分钟的短暂中断以及第 5 条约定的除外情形，不计入不可用分钟数。<span class="orderform_link">统计周期</span>内服务开通不满整周期的，按实际开通天数折算。
    3. <span class="header_3" id="2.3">监测与报告。</span>  <span class="coverpage_link">服务方</span>应当持续监测服务运行状态，保存不少于十二（12）个月的可用性记录，并应<span class="coverpage_link">客户</span>要求提供<span class="orderform_link">统计周期</span>的可用率报告。<span class="coverpage_link">客户</span>对报告数据有异议的，双方应本着诚实信用原则核对原始监测记录并协商确定。

3. <span class="header_2" id="3">故障等级与响应</span>
    1. <span class="header_3" id="3.1">故障分级。</span>  双方按照故障对<span class="coverpage_link">客户</span>业务的影响程度，将故障划分为以下等级：
        a. 一级故障：服务整体中断，或者核心功能完全不可用，导致<span class="coverpage_link">客户</span>业务全面停滞；
        b. 二级故障：服务的重要功能受损或者性能严重下降，<span class="coverpage_link">客户</span>业务受到重大影响但尚可部分开展；
        c. 三级故障：服务的非核心功能异常或者存在轻微缺陷，对<span class="coverpage_link">客户</span>业务影响有限。
    2. <span class="header_3" id="3.2">响应与修复时限。</span>  自<span class="coverpage_link">客户</span>通过约定支持渠道报障或者<span class="coverpage_link">服务方</span>监测发现故障之时起（以较早者为准），除封面页另有约定外：一级故障，<span class="coverpage_link">服务方</span>应在三十（30）分钟内响应，四（4）小时内修复或者提供可行的临时解决方案；二级故障，应在两（2）小时内响应，二十四（24）小时内修复或者提供可行的临时解决方案；三级故障，应在八（8）小时内响应，七十二（72）小时内修复或者列入版本修复计划并告知<span class="coverpage_link">客户</span>预计修复时间。自动回复不构成本条所称的响应。
    3. <span class="header_3" id="3.3">故障通报。</span>  发生一级、二级故障的，<span class="coverpage_link">服务方</span>应当及时向<span class="coverpage_link">客户</span>通报故障范围、影响和处理进展，并在故障消除后五（5）个工作日内提供书面故障报告，说明故障原因、处理过程和整改措施。
    4. <span class="header_3" id="3.4">升级机制。</span>  故障超过约定修复时限仍未消除的，<span class="coverpage_link">客户</span>有权要求<span class="coverpage_link">服务方</span>将故障处理升级至其技术负责人协调解决；<span class="coverpage_link">服务方</span>应当投入合理资源持续处理，直至故障消除。

4. <span class="header_2" id="4">服务积分补偿</span>
    1. <span class="header_3" id="4.1">积分计算。</span>  某一<span class="orderform_link">统计周期</span>的实际可用率低于<span class="orderform_link">可用率目标</span>的，<span class="coverpage_link">客户</span>有权按照下列标准获得服务积分，除封面页另有约定外：
        a. 实际可用率低于<span class="orderform_link">可用率目标</span>但不低于 99.0% 的，服务积分为该周期<span class="orderform_link">月度服务费</span>的 10%；
        b. 实际可用率低于 99.0% 但不低于 95.0% 的，服务积分为该周期<span class="orderform_link">月度服务费</span>的 25%；
        c. 实际可用率低于 95.0% 的，服务积分为该周期<span class="orderform_link">月度服务费</span>的 50%。
    2. <span class="header_3" id="4.2">申请程序。</span>  <span class="coverpage_link">客户</span>应当在相关<span class="orderform_link">统计周期</span>结束后三十（30）日内向<span class="coverpage_link">服务方</span>书面申请服务积分，并提供其掌握的故障时间等佐证信息；逾期未申请的，视为放弃该周期的服务积分。<span class="coverpage_link">服务方</span>应当在收到申请后十（10）个工作日内核实并书面答复。
    3. <span class="header_3" id="4.3">补偿方式与上限。</span>  服务积分用于抵扣<span class="coverpage_link">客户</span>后续应付的服务费用；服务到期不再续费或者<span class="keyterms_link">主协议</span>因<span class="coverpage_link">服务方</span>原因解除的，<span class="coverpage_link">客户</span>可以要求将未抵扣的服务积分折算为现金退还。单个<span class="orderform_link">统计周期</span>内累计服务积分不超过<span class="orderform_link">服务积分上限</span>。
    4. <span class="header_3" id="4.4">与其他救济的关系。</span>  服务积分是<span class="coverpage_link">客户</span>就未达到<span class="orderform_link">可用率目标</span>情形获得的首要补偿方式，但不排除<span class="coverpage_link">客户</span>依照第 7.2 条行使解除权，亦不免除<span class="coverpage_link">服务方</span>依法应当承担的其他违约责任；<span class="coverpage_link">客户</span>已获得的服务积分应当在计算同一事由的损失赔偿时相应扣减。

5. <span class="header_2" id="5">除外情形</span>
    1. <span class="header_3" id="5.1">除外范围。</span>  因下列原因导致的服务不可用或者指标不达标，不计入不可用分钟数，<span class="coverpage_link">服务方</span>不承担本协议项下的补偿责任：
        a. <span class="coverpage_link">服务方</span>提前至少七十二（72）小时通知的计划内维护，且每个<span class="orderform_link">统计周期</span>累计不超过八（8）小时；
        b. <span class="coverpage_link">客户</span>或其用户的设备、网络、软件故障，或者<span class="coverpage_link">客户</span>违反<span class="keyterms_link">主协议</span>约定使用服务；
        c. <span class="coverpage_link">客户</span>自备的第三方软硬件或者服务的故障；
        d. 不可抗力以及电信运营商骨干网络等基础设施故障；
        e. 依据法律法规或者有权机关的要求暂停服务；
        f. <span class="coverpage_link">服务方</span>为处置重大安全风险采取的紧急必要措施。
    2. <span class="header_3" id="5.2">举证与通知。</span>  <span class="coverpage_link">服务方</span>主张适用除外情形的，应当就相关事实承担举证责任，并在合理期限内向<span class="coverpage_link">客户</span>说明依据。

6. <span class="header_2" id="6">双方权利义务</span>
    1. <span class="header_3" id="6.1">服务方义务。</span>  <span class="coverpage_link">服务方</span>应当：
        a. 提供全天候（7×24 小时）的故障受理渠道；
        b. 按照本协议约定的时限响应和处理故障；
        c. 定期开展容量评估和灾备演练，持续保障服务达到<span class="orderform_link">可用率目标</span>。
    2. <span class="header_3" id="6.2">客户义务。</span>  <span class="coverpage_link">客户</span>应当：
        a. 通过约定支持渠道报障，并如实提供故障现象、发生时间和影响范围等必要信息；
        b. 对<span class="coverpage_link">服务方</span>的故障排查给予合理配合；
        c. 及时更新其联系人及联系方式，保证故障通报能够送达。
    3. <span class="header_3" id="6.3">配合迟延。</span>  因<span class="coverpage_link">客户</span>未及时提供必要配合导致故障处理迟延的，迟延期间不计入<span class="coverpage_link">服务方</span>的响应与修复时限。

7. <span class="header_2" id="7">违约责任</span>
    1. <span class="header_3" id="7.1">一般约定。</span>  一方不履行本协议义务或者履行义务不符合约定的，应当依法承担继续履行、采取补救措施或者赔偿损失等违约责任。
    2. <span class="header_3" id="7.2">解除权。</span>  发生下列情形之一的，<span class="coverpage_link">客户</span>有权书面通知<span class="coverpage_link">服务方</span>解除<span class="keyterms_link">主协议</span>项下受影响的服务订购，解除通知自到达时生效，<span class="coverpage_link">服务方</span>应当退还已预付但尚未消耗部分的服务费用：
        a. 连续三（3）个<span class="orderform_link">统计周期</span>实际可用率均低于<span class="orderform_link">可用率目标</span>的；
        b. 任一<span class="orderform_link">统计周期</span>实际可用率低于 95.0% 的；
        c. 一级故障超过约定修复时限四十八（48）小时仍未消除，致使合同目的不能实现的。
    3. <span class="header_3" id="7.3">责任上限。</span>  除法律规定不得限制责任的情形以及<span class="coverpage_link">服务方</span>故意或者重大过失造成损害的情形外，<span class="coverpage_link">服务方</span>就本协议项下全部事由承担的累计赔偿责任总额不超过<span class="keyterms_link">责任上限</span>。

8. <span class="header_2" id="8">期限与终止</span>
    1. <span class="header_3" id="8.1">期限。</span>  本协议的有效期与<span class="keyterms_link">主协议</span>项下相关服务的订购期限一致。
    2. <span class="header_3" id="8.2">终止后果。</span>  本协议终止的，终止前已经形成的服务积分、退费请求以及违约责任不因终止而消灭；第 4 条（服务积分补偿）就终止前的统计周期、第 7 条（违约责任）、第 9 条（适用法律与争议解决）以及第 11 条（释义）在本协议终止后继续有效。

9. <span class="header_2" id="9">适用法律与争议解决</span>
    1. <span class="header_3" id="9.1">适用法律。</span>  本协议适用中华人民共和国法律。
    2. <span class="header_3" id="9.2">争议解决。</span>  因本协议引起的或者与本协议有关的任何争议，双方应首先友好协商解决；自一方书面提出协商之日起三十（30）日内协商不成的，按照双方在封面页约定的<span class="keyterms_link">争议解决</span>方式（向有管辖权的人民法院提起诉讼，或者提交约定的仲裁机构仲裁）解决。

10. <span class="header_2" id="10">其他约定</span>
    1. <span class="header_3" id="10.1">通知。</span>  与本协议有关的通知应当以书面形式（包括电子邮件）发送至封面页载明的联系方式，自到达对方时发生效力；电子邮件自进入对方指定的电子邮箱系统之日视为到达。
    2. <span class="header_3" id="10.2">变更。</span>  对本协议的任何变更（包括调整<span class="orderform_link">可用率目标</span>、故障时限或者积分标准），须经双方书面确认后生效。
    3. <span class="header_3" id="10.3">可分性。</span>  本协议部分条款无效或者不可执行的，不影响其他条款的效力。
    4. <span class="header_3" id="10.4">弃权。</span>  一方未行使或者迟延行使本协议项下权利的，不视为放弃该权利；部分行使权利的，不妨碍该权利其余部分以及其他权利的行使。

11. <span class="header_2" id="11">释义</span>
    1. <span class="header_3" id="11.1">服务。</span>  指<span class="coverpage_link">服务方</span>依据<span class="keyterms_link">主协议</span>向<span class="coverpage_link">客户</span>提供的云服务或者软件在线服务，具体范围以<span class="keyterms_link">主协议</span>及其订单载明的内容为准。
    2. <span class="header_3" id="11.2">服务可用率。</span>  指按照第 2.2 条计算的、反映服务在<span class="orderform_link">统计周期</span>内可正常使用程度的百分比。
    3. <span class="header_3" id="11.3">服务积分。</span>  指实际可用率未达到<span class="orderform_link">可用率目标</span>时，<span class="coverpage_link">服务方</span>按照第 4 条向<span class="coverpage_link">客户</span>提供的、用于抵扣后续服务费用的补偿额度。
    4. <span class="header_3" id="11.4">响应。</span>  指<span class="coverpage_link">服务方</span>的技术支持人员就<span class="coverpage_link">客户</span>报障作出的有针对性的人工确认与初步处理答复，不包括系统自动回复。
    5. <span class="header_3" id="11.5">计划内维护。</span>  指<span class="coverpage_link">服务方</span>为升级、扩容或者例行检修目的，按照第 5.1(a) 条提前通知<span class="coverpage_link">客户</span>后实施的维护活动。
    6. <span class="header_3" id="11.6">不可抗力。</span>  指不能预见、不能避免且不能克服的客观情况，包括自然灾害、战争、大规模疫情、政府行为以及大范围电力、通信基础设施中断等。

*本范本由 Prelegal 起草（v1.0），由 AI 辅助生成，仅供参考，不构成法律意见；签署前请由执业律师审核。*
