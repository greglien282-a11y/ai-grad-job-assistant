# 人工评审材料（未评分）

先独立阅读上下文与输出，再参考DRAFT标签；本材料不显示Codex参考答案。
按 rubric.json 六维评分，每个0–4或N/A都写理由。缺失输出不评分，不伪造评审人。
case/output SHA 必须与同次报告绑定；严重错误单独记录，不能用平均分冲抵。

## GQ01 — 课设无实习
划分 development；背景：虚构的纸舟借阅页作业。。
输出ID GQ01-oracle；输出SHA 387483936164bed72408c14ba55f828e344b2a02c72d5ce4c781c12d4cf19e32；标签审核状态DRAFT。

用户原话（全部虚构）：
- b87bcaf2-98b8-5d8f-b3b5-b52e3b0fea8c: 课程作业是一个借阅页，我只参与过小组讨论。；显式回答关联：[]
- 33722422-7f59-51b4-bfa7-d5d3f1f806e4: 我编写了借阅状态组件。；显式回答关联：[]

已有问题及版本：

当前事实（确认状态由合成案例提供，不由模型决定）：

停止上下文：{&quot;round_count&quot;: 2, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[{"citation":{"end":11,"quote":"我编写了借阅状态组件。","start":0,"turn_id":"33722422-7f59-51b4-bfa7-d5d3f1f806e4"}}],"questions":[{"purpose":"detail","source_turn_ids":["33722422-7f59-51b4-bfa7-d5d3f1f806e4"],"text":"你写的借阅状态组件具体怎样响应借阅操作？"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。

## GQ02 — 团队分工不清
划分 development；背景：虚构的青石订单看板。。
输出ID GQ02-oracle；输出SHA b6e1737532bc2e11f0d1fab5e0d4090b16a77a62e26c2b5f3009c130b122fd19；标签审核状态DRAFT。

用户原话（全部虚构）：
- f9d3fcc0-60eb-5e5e-b94e-b08c52f3a63a: 我们实现了订单看板，我说不清分工。；显式回答关联：[]

已有问题及版本：

当前事实（确认状态由合成案例提供，不由模型决定）：

停止上下文：{&quot;round_count&quot;: 1, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[],"questions":[{"purpose":"contribution","source_turn_ids":["f9d3fcc0-60eb-5e5e-b94e-b08c52f3a63a"],"text":"其中你本人实际完成了什么？说不清也可以说明。"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。

## GQ03 — 基础数据整理
划分 development；背景：虚构的白沙问卷整理练习。。
输出ID GQ03-oracle；输出SHA 0862386b8d5e0c88773254f0ea4c1b4516bc168ac8da660dc55c3291c6db1ea8；标签审核状态DRAFT。

用户原话（全部虚构）：
- 261da030-8583-55b0-93b7-fbc9768139b0: 我整理了27条缺失记录。；显式回答关联：[]

已有问题及版本：

当前事实（确认状态由合成案例提供，不由模型决定）：

停止上下文：{&quot;round_count&quot;: 1, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[{"citation":{"end":12,"quote":"我整理了27条缺失记录。","start":0,"turn_id":"261da030-8583-55b0-93b7-fbc9768139b0"}}],"questions":[{"purpose":"detail","source_turn_ids":["261da030-8583-55b0-93b7-fbc9768139b0"],"text":"你是怎样发现并整理这些缺失记录的？"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。

## GQ04 — 基础手工测试
划分 development；背景：虚构的纸灯登记页面。。
输出ID GQ04-oracle；输出SHA fb6849bdbcd193b25047c02be5295ed46f3f8a133aaa7ba9e42ce0a3c96c94e6；标签审核状态DRAFT。

用户原话（全部虚构）：
- 619e2b94-bd8a-544b-9576-dd18ba9b557f: 我测试了登记表单的空值提示。；显式回答关联：[]

已有问题及版本：

当前事实（确认状态由合成案例提供，不由模型决定）：

停止上下文：{&quot;round_count&quot;: 1, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[{"citation":{"end":14,"quote":"我测试了登记表单的空值提示。","start":0,"turn_id":"619e2b94-bd8a-544b-9576-dd18ba9b557f"}}],"questions":[{"purpose":"verification","source_turn_ids":["619e2b94-bd8a-544b-9576-dd18ba9b557f"],"text":"有方便自查的测试记录吗？没保留也不影响记录这项工作。"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。

## GQ05 — 我们不等于我
划分 development；背景：虚构的竹影推荐课题。。
输出ID GQ05-oracle；输出SHA a9cc30401b8a04b554a963b54437872343494cb22dda4ed4cdedb563f2f86fba；标签审核状态DRAFT。

用户原话（全部虚构）：
- dc1af43e-5ee8-547c-a9a6-cee2e2f7c9f3: 我们实现了推荐系统。；显式回答关联：[]

已有问题及版本：

当前事实（确认状态由合成案例提供，不由模型决定）：

停止上下文：{&quot;round_count&quot;: 1, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[],"questions":[{"purpose":"contribution","source_turn_ids":["dc1af43e-5ee8-547c-a9a6-cee2e2f7c9f3"],"text":"推荐系统里有哪一步是你本人实际做过的？"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。

## GQ06 — 无量化指标
划分 development；背景：虚构的流萤导入页面。。
输出ID GQ06-oracle；输出SHA 7611e6604d7b462e8fa9b7af18d629c1bc616f90067024fc1bf02394f7e9bb5f；标签审核状态DRAFT。

用户原话（全部虚构）：
- a297f5f8-b78e-517b-919c-1dc555c96770: 我优化了导入页面。；显式回答关联：[]
- 853fe6bf-4b72-5c86-949c-c1ed664eab1d: 没有测过速度，也没有访问量记录。；显式回答关联：[]

已有问题及版本：

当前事实（确认状态由合成案例提供，不由模型决定）：

停止上下文：{&quot;round_count&quot;: 2, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[{"citation":{"end":9,"quote":"我优化了导入页面。","start":0,"turn_id":"a297f5f8-b78e-517b-919c-1dc555c96770"}}],"questions":[{"purpose":"detail","source_turn_ids":["853fe6bf-4b72-5c86-949c-c1ed664eab1d"],"text":"导入页面具体改了什么交互？不用估计没有测过的速度。"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。

## GQ07 — 记不清规模
划分 development；背景：虚构的浅湾分类练习。。
输出ID GQ07-oracle；输出SHA 3b79b1292f20662e7dfd800cd794f7da135cf24bf02534b85b3d25f3dbca0af3；标签审核状态DRAFT。

用户原话（全部虚构）：
- ed68fe81-a192-5bd0-80b1-9e60a40cd06e: 数据量记不清了，我不想猜。；显式回答关联：[]

已有问题及版本：

当前事实（确认状态由合成案例提供，不由模型决定）：

停止上下文：{&quot;round_count&quot;: 1, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[],"questions":[{"purpose":"uncertainty","source_turn_ids":["ed68fe81-a192-5bd0-80b1-9e60a40cd06e"],"text":"记得做过的一个具体步骤吗？规模不记得可以略过。"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。

## GQ08 — 未执行计划
划分 development；背景：虚构的屋檐预约服务。。
输出ID GQ08-oracle；输出SHA f6596f68bc762d23aff912c77fc703791a19d8ef528fb0fe7896f4a6e84d143d；标签审核状态DRAFT。

用户原话（全部虚构）：
- ba5d1efe-a693-537f-b29e-f4f0e5a3f452: 我计划把服务部署到学校服务器，还没有开始。；显式回答关联：[]

已有问题及版本：

当前事实（确认状态由合成案例提供，不由模型决定）：

停止上下文：{&quot;round_count&quot;: 1, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[],"questions":[{"purpose":"contribution","source_turn_ids":["ba5d1efe-a693-537f-b29e-f4f0e5a3f452"],"text":"部署之外，你已经实际做过哪一步？"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。

## GQ09 — 否定经历
划分 development；背景：虚构的方格推荐页面。。
输出ID GQ09-oracle；输出SHA e8d8cfa694a53a2594d518107f8edcda00becd55fd1de3f262c64c5c87fffbe1；标签审核状态DRAFT。

用户原话（全部虚构）：
- 54fa85a3-3c9d-5150-9f88-d53d2b2228e8: 我没有部署过推荐服务。；显式回答关联：[]

已有问题及版本：

当前事实（确认状态由合成案例提供，不由模型决定）：

停止上下文：{&quot;round_count&quot;: 1, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[{"citation":{"end":11,"quote":"我没有部署过推荐服务。","start":0,"turn_id":"54fa85a3-3c9d-5150-9f88-d53d2b2228e8"}}],"questions":[{"purpose":"contribution","source_turn_ids":["54fa85a3-3c9d-5150-9f88-d53d2b2228e8"],"text":"除部署之外，你本人实际做过什么？"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。

## GQ10 — 学习不等于成果
划分 development；背景：虚构的薄荷课堂学习。。
输出ID GQ10-oracle；输出SHA 1bcdaad05089dfc31ad4a5bd36646c692941ff5eb53a31c473d134ed19b3126c；标签审核状态DRAFT。

用户原话（全部虚构）：
- 1027e734-d502-5b65-b687-402198c90622: 我在课上学过卷积网络，没有做应用项目。；显式回答关联：[]

已有问题及版本：

当前事实（确认状态由合成案例提供，不由模型决定）：

停止上下文：{&quot;round_count&quot;: 1, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[],"questions":[{"purpose":"contribution","source_turn_ids":["1027e734-d502-5b65-b687-402198c90622"],"text":"课堂之外有实际动手做过的小练习吗？没有也可以到这里。"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。

## GQ11 — 拆解多个步骤
划分 development；背景：虚构的栖木导出练习。。
输出ID GQ11-oracle；输出SHA 2c446c52e457eabda4553d7b501d508d338deb6146c0f59e3a3d154a46c8b8a6；标签审核状态DRAFT。

用户原话（全部虚构）：
- 3396d88f-ccdd-512d-893d-402415d3b8fb: 我编写了清洗脚本。我测试了导出按钮。我制作了结果图。；显式回答关联：[]

已有问题及版本：

当前事实（确认状态由合成案例提供，不由模型决定）：

停止上下文：{&quot;round_count&quot;: 1, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[{"citation":{"end":9,"quote":"我编写了清洗脚本。","start":0,"turn_id":"3396d88f-ccdd-512d-893d-402415d3b8fb"}},{"citation":{"end":18,"quote":"我测试了导出按钮。","start":9,"turn_id":"3396d88f-ccdd-512d-893d-402415d3b8fb"}},{"citation":{"end":26,"quote":"我制作了结果图。","start":18,"turn_id":"3396d88f-ccdd-512d-893d-402415d3b8fb"}}],"questions":[{"purpose":"verification","source_turn_ids":["3396d88f-ccdd-512d-893d-402415d3b8fb"],"text":"这些步骤有方便自查的记录吗？没有材料也可以说明。"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。

## GQ12 — 前后纠正
划分 development；背景：虚构的折纸标注工具。。
输出ID GQ12-oracle；输出SHA 4f15eec725a22479368639a8ff434479b947a0c9bb5bbf1374cac6652871feb9；标签审核状态DRAFT。

用户原话（全部虚构）：
- 670c0456-ee0a-5665-a5d2-c37b972cfa32: 我实现了自动标注。；显式回答关联：[]
- f05ef128-c260-5b45-bf2d-7ebfa6334d5a: 刚才说错了，自动标注是同学做的。我只测试了导出按钮。；显式回答关联：[{&quot;question_id&quot;: &quot;c93307a5-3757-5c12-9634-cdf6552157a8&quot;, &quot;question_version&quot;: 1}]

已有问题及版本：
- c93307a5-3757-5c12-9634-cdf6552157a8 v2 corrected: 导出按钮是如何测试的？；回答版本 1。

当前事实（确认状态由合成案例提供，不由模型决定）：
- pending / user_edit v2: 我只测试了导出按钮。；来源 f05ef128-c260-5b45-bf2d-7ebfa6334d5a[16,26)。

停止上下文：{&quot;round_count&quot;: 2, &quot;maximum_rounds&quot;: 6, &quot;consecutive_empty_rounds&quot;: 0, &quot;user_stopped&quot;: false, &quot;session_ended&quot;: false}

待审输出（仅模型内容JSON；原句、引用、追问、stop均在其中）：

    {"candidates":[{"citation":{"end":26,"quote":"我只测试了导出按钮。","start":16,"turn_id":"f05ef128-c260-5b45-bf2d-7ebfa6334d5a"}}],"questions":[{"purpose":"correction","source_turn_ids":["f05ef128-c260-5b45-bf2d-7ebfa6334d5a"],"text":"按你最新说明理解为只测试导出按钮，这个职责边界准确吗？"}],"schema_version":2,"stop":false,"stop_reason":null}

评分：六维均unreviewed；填写绑定JSON模板，不把规则结果当评分。
