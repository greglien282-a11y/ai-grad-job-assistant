# M1-2C-2 供应商/API 预研（不做选择或调用）

核对日期：2026-10-14。只查官方公开文档，没有打开控制台、读取密钥、充值或调用模型。下列价格仅供设计预算，非已批准费用/报价，汇率、缓存、处理档位、区域、思考输出和促销会改变总额；接入前必须按固定模型/区域复核。中文经历挖掘质量均 **未实测**，不依据宣传排序。

## OpenAI API

Responses/Chat 的 Structured Outputs 支持 JSON Schema（需单独核对所选模型支持及 schema 子集），能比仅合法 JSON 更早发现形状错误；仍需本 PR 的来源、语义边界、数字与版本校验。[官方结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)。

价格页面列出 gpt-6.1-sol 短上下文示例输入 $2/百万 token、输出 $10/百万 token，其他处理档位/长上下文价格不同；这里只作为公开价格样本，并没有选定该模型。真实评测需用同一中文样本检查追问价值、否定/团队归属和 JSON/引用通过率。[官方价格](https://developers.openai.com/api/docs/pricing)。

RPM/TPM 等限制依模型、项目/组织与账户档位，不能把文档示例当成本账号额度。应用需显式短超时、禁止 SDK 默认写重试，把未知结果交给 GET/用户确认重试，而非追求服务默认长等待。[官方限流](https://developers.openai.com/api/docs/guides/rate-limits)。

API 数据默认不用于训练（除非主动选择共享）；滥用监测默认可能保留最多 30 天，应用状态留存取决于端点/选项；ZDR 需要资格且不是所有功能可用。未来必须审查 store/背景任务等选项及账号地区，不能笼统承诺零留存。[官方数据控制](https://developers.openai.com/api/docs/guides/your-data)。

## DeepSeek API

Chat 文档的 JSON Output 保证合法 JSON，但不等于本业务 Schema/语义正确；Responses 文档虽列出结构化入口，本轮没有验证任何真实端点的 schema 子集。后续需要固定 API 类型的合同测试，不能假定 OpenAI 兼容就完全相同。[官方 JSON 模式](https://api-docs.deepseek.com/guides/json_mode/)。

当前价格文档示例 deepseek-flash（映射到 V4.1-Flash）：缓存未命中输入非高峰 $0.15/百万、高峰 $0.30/百万，输出 $0.60/$1.20；V4-Pro 输入 $0.66/$1.32、输出 $1.98/$3.96。高峰时段、缓存命中及别名变化会影响预算；不选定、不购买，中文质量仍需同一批样本实测。[官方模型/价格](https://api-docs.deepseek.com/quick_start/pricing/)。

官方并发说明示例 Flash 2500、Pro 500，超限 429；可能使用 keep-alive 等待，未开始推理十分钟后关闭连接。Pathwise 现有 45 秒调用/60 秒租约明显更短，需显式客户端超时、取消后的 unknown 恢复，而不能盲目采用供应商等待时间。[官方并发与连接机制](https://api-docs.deepseek.com/quick_start/rate_limit/)。

公开通用隐私政策不是 Pathwise 下游用户的完整处理条款，也不能据此推断 API 专属无训练/零留存承诺；API/DPA、处理区域、保留期限与退出机制仍需单独核验，未满足前不外发真实资料。[官方隐私政策](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)。

## 阿里云百炼 / 千问

官方提供 json_object 与 json_schema/strict；json_object 不保证字段结构，json_schema 的支持依模型/输入方式，多模态可能降级。后续只用文本输入核对固定模型、API 与区域；中文质量同样需要原话/否定/贡献/追问评测，不能只根据中文产品定位决定。[官方结构化输出](https://help.aliyun.com/zh/model-studio/qwen-structured-output)。

价格示例 qwen-plus 全球部署、0–128K 输入阶梯：输入 0.8 元/百万 token，非思考输出 2 元、思考输出 8 元；其他部署区域/模型阶梯不同。不假设免费额度有效或已授权使用。[官方价格](https://help.aliyun.com/zh/model-studio/model-pricing)。

RPM/TPM 与模型版本/部署模式有关，需按实际账户复核；未购/未调用，不提供实测延迟。应用统一短超时、429 回退到恢复/手工流程，不自动再次推理。[官方限流](https://help.aliyun.com/zh/model-studio/rate-limit)。

官方隐私说明声明不把客户数据用于模型训练；国际站企业 API 留存说明有默认缓存/安全数据窗口及有条件 ZDR，不能套用到所有地区/模型/账号，也不能把“不训练”解释为“不留存”。[隐私说明](https://help.aliyun.com/zh/model-studio/privacy-notice)、[国际站留存政策](https://www.alibabacloud.com/help/en/model-studio/data-retention-policy)。

## 下一阶段的共同门禁

负责人确认候选 API/区域/固定版本、真实测试费用上限及可发送的合成字段后，才实现服务器适配器与受控密钥注入。先验证通用 Schema 到供应商子集的映射、UTF-8/中文 token 估算、超时与 429/5xx/截断/拒答，不能开启无条件 SDK 重试或按未知价格预留预算。

同一批合成评测至少记录：非法/伪造事实数、错误引用/位置数、否定/团队贡献丢失数、原子候选通过率、同义重复/无价值追问数、记不清/跳过后的停止行为、原话纠正后的准确性、中文可读性、p50/p95 时延与实际 token/费用。具体通过阈值应在真实调用前审查；不能把本轮 Fake 的通过率当作供应商模型质量。

## M1-2C-2 最新设计决议

优先级已更新为 DeepSeek 官方 V4.1-Flash 首选、百炼第二渠道（同模型 DeepSeek 或 Qwen），详见 [分层配置与评测/费用设计](M1_2C_2_ADAPTER_EVAL_DESIGN.md)。本文是早期预研摘要；留存政策、端点和预算以新设计复核为准，所有真实调用仍未授权。
