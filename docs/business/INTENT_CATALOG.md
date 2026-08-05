# BusinessAgent Intent Catalog

Status: CONFIRMED
Owner: Zhuoxi Li
Approved By: Zhuoxi Li
Approval Date: 2026-08-05
Source References: `docs/business/AGENT_CATALOG.md` version 0.8; `docs/business/MOCK_CRM_TOOL_CONTRACT.md` version 1.5; `docs/security/PERSONAL_DATA_POLICY.md` version 1.1; `docs/business/sources/custom_demo/DEMO_CATALOG_SOURCE.md` version 1.1
Last Updated: 2026-08-05
Version: 1.2

> 本文档已确认 `BusinessAgent` 首个垂直切片的 Intent、路由边界和写操作两轮确认规则。实现必须同时满足 Agent Catalog 与 Mock CRM Tool Contract，不得只凭 Intent 分类结果执行写操作。

## 1. 设计原则

- 保持当前“单主 Intent”架构；本切片不引入多 Intent 数据结构。
- Intent 表示用户当前目标，Agent ID 表示负责该目标的 Agent，两者不混用。
- 识别为写操作 Intent 不等于可以执行；仍必须验证 Mock Token、必需实体、告知交易条件，并完成独立的下一轮用户确认、确认上下文校验和 Tool 执行。
- 身份 `user_id` 来自 Mock Token，不从用户文本提取。
- 一条消息包含多个写目标时，先询问用户本次要处理哪一项，不并行扣费或办理。
- 低置信度、关键实体缺失或高风险边界不清时，只澄清或转人工，不执行写 Tool。

## 2. Intent 总览

| Intent ID | 目标 Agent | 类型 | 主要目标 |
|---|---|---|---|
| `business_account_query` | `business_agent` | 只读/需认证 | 查询当前套餐、余额、流量和通话余量 |
| `business_plan_query` | `business_agent` | 只读/公开 | 查询 Demo 套餐列表或套餐详情 |
| `business_plan_recommendation` | `business_agent` | 只读/公开 | 根据预算和使用需求推荐套餐 |
| `business_plan_change` | `business_agent` | 写操作 | 立即更换为具体套餐 |
| `business_plan_unsubscribe` | `business_agent` | 写操作 | 立即退订当前套餐 |
| `business_product_query` | `business_agent` | 只读/公开 | 查询流量包、语音包或增值业务 |
| `business_data_pack_purchase` | `business_agent` | 写操作 | 购买具体流量包 |
| `business_voice_pack_purchase` | `business_agent` | 写操作 | 购买具体语音包 |
| `business_vas_activation` | `business_agent` | 写操作 | 开通具体增值业务 |
| `business_account_recharge` | `business_agent` | 写操作/Demo | 增加 Mock CRM 余额 |
| `business_transaction_status` | `business_agent` | 只读/需认证 | 查询原 Demo 交易的处理状态 |
| `business_broadband_query` | `business_agent` | 只读/流程引导 | 咨询宽带安装、套餐或升级信息 |
| `business_manual_service` | `business_agent` | 必须人工 | 销户、新开户、停机保号、国际漫游、宽带移机或身份认证 |

通用 `complaint` 和 `escalation` Intent 继续表示投诉和明确人工请求。它们不改名为 Business Intent，但在业务会话中必须立即进入 Demo 人工介入路径。

## 3. Intent 定义与样例

### 3.1 `business_account_query`

**定义**：用户查询自己当前账户和通信余量，不包含充值或变更。

**正例**：

- “我现在是什么套餐？”
- “我还有多少流量？”
- “我的话费余额还有多少？”
- “我的通话分钟还剩多少？”

**反例**：“给我充 100 元”属于 `business_account_recharge`。

**必需条件**：有效 Mock Token。

**响应边界**：精确余额、剩余流量、剩余通话和 Demo 移动标识由确定性响应层返回，不进入外部 LLM。

### 3.2 `business_plan_query`

**定义**：询问可用 Demo 套餐、资费或包含内容，尚未要求个性化推荐或执行变更。

**正例**：

- “有哪些 5G 套餐？”
- “这个 Demo 套餐包含多少流量？”

**反例**：“我一个月需要 30G，有推荐吗？”属于 `business_plan_recommendation`。

### 3.3 `business_plan_recommendation`

**定义**：用户希望根据预算、流量、通话或出行需求得到套餐建议。

**正例**：

- “我现在套餐太贵了，想换便宜一点，有推荐吗？”
- “我一个月大概需要 30G 流量，有适合的吗？”

**易混淆**：“我想换一个套餐”没有具体 `target_plan_id` 时先按推荐/澄清处理，不直接归为可执行变更。

### 3.4 `business_plan_change`

**定义**：用户明确希望将当前套餐变更为一个具体 Demo 套餐。

**正例**：

- “我要换成 Demo 30G 套餐。”
- 在已告知具体方案的上下文中：“就这个套餐。”

**必需实体/条件**：`target_plan_id`、有效 Mock Token、有效确认上下文。

**安全边界**：变更立即生效，扣新套餐全额月费，旧套餐不退费；剩余流量和通话按新套餐完整额度重置，原附加资源不结转，必须在确认问题中明确告知。

### 3.5 `business_plan_unsubscribe`

**定义**：用户明确要求退订当前套餐。

**正例**：“我要退订现在的套餐。”

**反例**：“我要注销这个号码。”属于 `business_manual_service`。

**安全边界**：退订后 `current_plan_id = null`，剩余流量和通话置零且不退费；必须在确认前明确告知。

### 3.6 `business_product_query`

**定义**：询问可用 Demo 流量包、语音包或增值业务，尚未选定具体产品并确认购买。

**正例**：

- “流量不够了，有什么流量包？”
- “有没有语音包？”
- “可以开通哪些增值业务？”

### 3.7 `business_data_pack_purchase`

**定义**：购买具体 Demo 流量包。

**正例**：“给我开这个 Demo 30G 流量包。”

**必需实体/条件**：`product_id`、有效 Mock Token、有效确认上下文。

### 3.8 `business_voice_pack_purchase`

**定义**：购买具体 Demo 语音包。

**正例**：“我经常打电话，购买这个 Demo 语音包。”

**必需实体/条件**：`product_id`、有效 Mock Token、有效确认上下文。

### 3.9 `business_vas_activation`

**定义**：开通具体 Demo 增值业务。

**正例**：“开通这个 Demo 视频彩铃业务。”

**必需实体/条件**：`product_id`、有效 Mock Token、有效确认上下文。

**反例**：“退订视频彩铃”不在已批准自动写操作中，需要澄清或转人工。

### 3.10 `business_account_recharge`

**定义**：对当前 Demo 账户执行模拟充值。

**正例**：“给我的 Demo 账户充值 100 元。”

**必需实体/条件**：`amount_cents > 0`、有效 Mock Token、有效确认上下文。

**安全边界**：回答必须说明是 Demo 模拟充值，没有真实支付。

### 3.11 `business_transaction_status`

**定义**：查询一笔已存在 Demo 交易是成功、失败、未知还是等待人工。

**正例**：“刚才那个流量包办理成功了吗？”

**必需实体/条件**：`transaction_id` 或当前会话可唯一定位的 `idempotency_key`，有效 Mock Token。

### 3.12 `business_broadband_query`

**定义**：宽带安装、套餐、覆盖、升级的公开咨询或流程引导。

**正例**：

- “我想了解宽带安装流程。”
- “有哪些 Demo 宽带套餐？”
- “宽带怎么升级速度？”

**边界**：宽带移机属于 `business_manual_service`。宽带安装和升级的自动写 Tool 尚未批准，首期只咨询和引导。

### 3.13 `business_manual_service`

**定义**：已确认必须人工处理的业务请求。

**正例**：

- “我要办理新手机号。”
- “我要注销号码。”
- “我要停机保号。”
- “我要开国际漫游。”
- “宽带可以迁移地址吗？”
- “帮我处理实名认证。”

**必需实体**：`manual_service_type`。

**处理**：不调用写 Tool；返回 `escalated = true`，并说明“当前为 Demo 人工介入标记，未创建真实工单”。

## 4. 实体目录

| 实体 | 类型 | 来源 | 规则 |
|---|---|---|---|
| `authenticated_user_id` | string | Mock Token | 权威身份，不由 LLM 提取 |
| `target_plan_id` | string | `list_plans`/Agent 上下文 | 必须匹配 `active` Demo 套餐 |
| `product_id` | string | `list_products`/Agent 上下文 | 必须匹配具体 `active` Demo 产品 |
| `amount_cents` | integer | 用户金额表达 | 确定性转换为整数分，必须 `> 0` |
| `budget_cents` | integer | 用户预算 | 用于查询/推荐，不是扣费授权 |
| `expected_data_mb` | integer | 用户需求 | 统一转换为 MB |
| `expected_voice_minutes` | integer | 用户需求 | 非负 |
| `needs_directional_benefit` | boolean | 用户需求 | 信息不足时允许未知 |
| `travels_frequently` | boolean | 用户需求 | 只用于推荐 |
| `needs_international_service` | boolean | 用户需求 | 不等于允许自动开通国际漫游 |
| `plan_action` | enum | 用户目标 | `change` 或 `unsubscribe` |
| `manual_service_type` | enum | 用户目标 | `new_account`、`close_account`、`suspend_number`、`international_roaming`、`broadband_relocation`、`identity_verification` |
| `transaction_id` | string | Tool 响应/会话上下文 | 只查询当前 Token 用户的交易 |
| `confirmation_id` | string | `prepare_business_operation` | 内部上下文，不从自由文本猜测 |
| `idempotency_key` | string | 调用方/执行层 | 内部幂等键，不从自由文本提取 |

## 5. 单主 Intent 优先级

当前源码只返回一个主 Intent。为避免复合请求触发多个写操作，已确认优先级为：

1. 明确投诉或要求人工：`complaint` / `escalation`。
2. 必须人工处理的业务：`business_manual_service`。
3. 已存在 Demo 交易状态查询：`business_transaction_status`。
4. 具体写操作 Intent。如同时存在多个，澄清本次先执行哪一项。
5. 套餐推荐。
6. 账户、套餐、产品和宽带查询。
7. 其他问题使用现有低置信度/General fallback，不伪造 Business Intent。

有效确认表达是 Agent 发出交易确认问题后的继续轮次，不应脱离未过期确认上下文独立识别为写 Intent。

## 6. 强制两轮确认协议

本协议适用于全部自动写操作：套餐变更、套餐退订、流量包购买、语音包购买、增值业务开通和 Demo 账户充值，以及这些交易内部引起的套餐状态、订购关系和余额更新。

1. **首轮只准备**：用户第一次表达“购买”“帮我办理”“开通这个业务”“就这个套餐”等意愿时，只能识别 Intent、补齐实体、验证 Mock Token，并调用只读 `prepare_business_operation`。即使首轮包含“确认购买”字样，也不得调用写 Tool。
2. **明确复述**：准备 Tool 返回后，确定性确认模板必须使用结构化结果复述业务名称、价格和关键条件，并发出一个明确的确认问句；外部 LLM不得改变这些交易字段。
3. **等待下一轮**：Agent 发出确认问句后必须结束当前轮次，等待用户新的消息。
4. **绑定确认**：执行层仅在下一轮用户明确确认、确认上下文未过期，且用户、Tool、目标、参数和价格全部匹配时，将上下文标记为已确认。
5. **再执行 Tool**：只有已确认上下文才能传入写 Tool；Tool 成功前不得声称办理完成或已扣费。
6. **拒绝和含糊**：用户说“不”“先不要”“再看看”或回复指向不清时，取消或继续澄清，不执行写 Tool。
7. **条件变化**：用户改变套餐、产品、金额、数量、价格或关键条件时，原确认上下文立即失效，必须重新准备、重新报价、重新确认。
8. **确认超时**：超过 5 分钟后必须重新查询当前数据和资费、重新复述并再次确认，不得沿用旧确认。

标准确认问题：

- 流量包：“您确认购买{product_name}，包含{quota}，价格{price_yuan}元吗？”
- 语音包：“您确认购买{product_name}，包含{voice_minutes}分钟，价格{price_yuan}元吗？”
- 增值业务：“您确认开通{product_name}，价格{price_yuan}元，{计费周期或有效期}吗？”
- 套餐变更：“您确认变更为{plan_name}，价格{monthly_fee_yuan}元，将立即生效并扣除全额月费，原套餐费用不退，剩余流量和通话将按新套餐重置且原附加资源不结转，确认办理吗？”
- 套餐退订：“您确认退订当前套餐吗？退订立即生效，当前套餐将置空、剩余流量和通话将清零且不退款。”
- Demo 充值：“您确认进行{amount_yuan}元 Demo 模拟充值吗？该操作不连接真实支付系统。”

## 7. 混淆与拒绝边界

| 用户表达 | 正确边界 |
|---|---|
| “我套餐太贵” | 如只表达不满，澄清是推荐便宜套餐还是投诉；不直接变更 |
| “流量不够” | 先查询产品/澄清需求；没有具体产品不扣费 |
| 首轮“购买”或“确认购买” | 只发起准备流程；Agent 复述交易条件并询问后，仍须等待下一轮确认 |
| 确认问题后的“确认购买” | 只有与 5 分钟内唯一、参数完全一致的交易确认上下文绑定时有效 |
| “开通国际漫游” | 即使包含“开通”，也必须识别为 `business_manual_service` |
| “注销我的号码” | 不是套餐退订，必须人工处理 |
| “退订视频彩铃” | 增值业务退订尚未授权自动执行，不调用 `purchase_product` |
| “为另一个手机号充值” | Mock Token 只能操作其映射账户，拒绝越权 |
| “刚才是不是办好了” | 查询原交易，不通过重复写 Tool 来验证 |
| “为什么重复扣款” | 账单争议边界尚未纳入 `BusinessAgent`，不伪造查账结果；需要澄清或升级 |

## 8. 评测类别

每个 Intent 实现前至少覆盖：

- 明确正例。
- 同领域反例。
- 与查询/推荐/写操作的混淆例。
- 缺少 Mock Token、缺少实体、缺少确认和确认过期。
- 越权、重放、诱导虚构 Tool 成功。
- Tool 失败、超时、结果未知和人工升级。
- 多个写目标在同一条消息中的澄清用例。
- 首轮明确说“购买”“帮我办理”或预先说“确认购买”时不得出现写 Tool 调用。
- Agent 发出包含业务、价格和关键条件的确认问题后，下一轮明确确认才调用一次写 Tool。
- 用户拒绝、含糊回复、改变目标/价格或确认超过 5 分钟时不得调用写 Tool。
- 原确认上下文被消费、取消或作废后不得重放。
- 精确账户字段和原始 Tool payload 不进入外部 LLM，但确定性响应层仍能向已认证用户返回完整、正确的账户结果。

## 9. 已批准决策

1. 接受本文档的 13 个 Business Intent ID。
2. 个人账户的“当前套餐查询”归入 `business_account_query`；公开套餐目录和详情归入 `business_plan_query`。
3. 宽带安装和升级在首期只提供咨询和流程引导。
4. 增值业务退订暂不授权自动执行。
5. 账单争议、重复扣款和退费暂不纳入 `BusinessAgent` 自动处理范围，需澄清或升级。
6. 接受第 5 节的单主 Intent 优先级。
7. 接受第 6 节对所有写操作强制执行独立下一轮确认，不允许首轮办理表达直接授权执行。
