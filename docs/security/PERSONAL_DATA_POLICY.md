# EchoMind Personal Data Policy

Status: CONFIRMED
Owner: Zhuoxi Li
Approved By: Zhuoxi Li
Approval Date: 2026-08-05
Source References: `docs/business/AGENT_CATALOG.md` version 0.8; `docs/business/INTENT_CATALOG.md` version 1.2; `docs/business/MOCK_CRM_TOOL_CONTRACT.md` version 1.5
Last Updated: 2026-08-05
Version: 1.1

> 本政策只适用于 EchoMind Demo 环境中的 `BusinessAgent`、Mock CRM、Tool、外部 LLM、日志、Redis、ChromaDB、测试与评测。当前环境不得接入、导入或衍生自真实运营商用户的个人数据。

## 1. 适用范围与原则

适用业务包括：

- 账户查询。
- 套餐查询、推荐、变更和退订。
- 流量包、语音包和增值业务查询或购买。
- Demo 账户充值。
- 上述业务产生的确认上下文、交易状态、日志、Memory 和评测数据。

统一原则：

- 只处理完成业务流程所需的最少数据。
- 所有账户数据必须是纯合成 Demo 数据，不得使用真实数据的脱敏、采样、映射或派生结果。
- 公开业务资料与合成账户数据分开管理，不得把公开套餐资料标记为用户账户数据。
- 精确账户数据只能在受信任执行层和确定性响应层处理，不发送给外部 LLM。
- 不得为了调试、评测或改善回答而扩大数据采集、输出或保留范围。
- 安全限制不得通过删除业务能力来实现；获批的账户查询和写操作必须通过受控链路完整实现并通过测试。

## 2. 数据分级

| 级别 | 数据类型 | 示例 | 允许范围 |
|---|---|---|---|
| `D0_PUBLIC` | 公开或自定义 Demo 业务资料 | 套餐名称、公开价格、额度、产品说明 | 可发送外部 LLM，可进入知识库 |
| `D1_PSEUDONYMOUS` | 合成、匿名且不含精确账户值的会话数据 | `anonymous_user_id`、Intent、用户主动提供的预算和需求 | 按本政策发送外部 LLM或进入受控存储 |
| `D2_PROTECTED_DEMO` | 精确合成账户与交易数据 | Mock CRM `user_id`、余额、剩余量、订购关系、交易 ID | 仅受信任执行层、Mock CRM 和确定性响应层 |
| `D3_PROHIBITED` | 真实个人数据和秘密 | 真实手机号、姓名、证件、地址、支付信息、真实或生产 Token、Secret | 当前项目任何位置均禁止使用 |

`D2_PROTECTED_DEMO` 虽然是合成数据，仍按受保护账户数据处理，以保证未来迁移时不会形成错误的数据流。

## 3. 外部 LLM 数据边界

### 3.1 允许发送

- 会话级 `anonymous_user_id`，不得发送 Mock CRM 稳定 `user_id`。
- 公开或自定义 Demo 套餐、流量包、语音包和增值业务资料。
- 当前套餐的公开名称、公开月费和公开包含内容。
- 用户主动提供的预算、预计流量、预计通话和业务偏好。
- 登录状态布尔值，不包含 Token 或认证 Header。
- 脱敏后的 Intent、Agent 类型和业务状态，例如“余额充足”“余额不足”“已订购”。
- 标准化错误类型和是否需要人工介入，不包含内部堆栈或原始 Tool payload。

### 3.2 禁止发送

- Mock CRM `demo_user_id`、`mobile_alias` 和稳定账户关联键。
- 精确余额、剩余流量、剩余通话分钟和账户版本号。
- 交易 ID、幂等键、确认上下文完整内容和内部参数哈希。
- 完整或掩码后的真实手机号、真实姓名、证件、银行卡、支付、地址、订单和账单数据。
- Mock Token、Authorization Header、API Key、数据库密码和任何 Secret。
- 原始数据库记录、内部字段清单、异常堆栈和未授权内部规则。

外部 LLM 不得接收原始 `get_account_summary` 或写 Tool 响应。发送前必须经过显式 allowlist 投影；未知字段默认丢弃。

## 4. 精确账户数据的确定性响应层

精确账户数据必须通过以下链路返回：

```text
已认证请求
  → 受信任执行层验证 Mock Token
  → Tool 查询 Mock CRM
  → 将结果拆分为 LLM 可见数据和受保护账户数据
  → 确定性响应层使用固定模板组装精确字段
  → 返回给当前已认证用户
```

确定性响应层负责：

- 当前精确余额。
- 当前剩余流量。
- 当前剩余通话分钟。
- 当前账户对应的 Demo 移动标识。
- Demo 交易 ID 和可查询的交易状态。
- 写 Tool 的最终成功、失败、未知或人工介入结果。

实现要求：

- 精确字段不进入 Prompt、LLM Tool 消息、对话摘要、日志、ChromaDB 或评测报告。
- 响应模板只能读取结构化 Tool 字段，不拼接原始数据库记录或异常信息。
- 身份验证、账户归属校验和 Tool 成功状态必须在模板渲染前完成。
- 确定性响应层失败时不得把原始数据转交外部 LLM作为 fallback；应返回安全的暂不可用提示，并按合同进入查询状态或人工介入路径。
- 对外响应仍须完整实现账户查询能力，不能只返回“充足/不足”来替代用户明确请求的精确余额或剩余量。

套餐推荐可以使用用户主动提供的需求和 `D0_PUBLIC` 套餐信息；不得为了推荐而向外部 LLM暴露精确账户余额或剩余量。

## 5. 标识符与手机号规则

- Mock CRM 内部用户 ID 使用 `demo_user_001` 形式，必须以 `demo_` 开头。
- Demo 移动标识使用 `DEMO_MOBILE_001` 形式，不使用 `138****5678` 等真实手机号外观。
- 外部 LLM、应用日志和一般会话 Memory 只使用会话级 `anonymous_user_id`。
- `anonymous_user_id` 必须由受信任执行层生成，不得包含或直接编码 Mock CRM `user_id`，并随会话轮换。
- Mock Token 只在认证边界读取，不得复制到请求模型、Prompt、Memory、日志、交易快照、错误响应或 Agent 输出。
- 公开静态 `DEMO_TOKEN_` 不是生产秘密，只允许存在于只读纯合成种子文件的 `mock_tokens` 映射中；任何真实、外部系统或生产 Token 均禁止进入仓库。

## 6. 存储与保留规则

### 6.1 Mock CRM

允许保存完成 Demo 功能所需的 `D2_PROTECTED_DEMO` 数据，包括精确余额、剩余量、套餐关系、订购关系和交易记录。

- 仓库种子文件：`data/demo_crm/mock_crm.json`，只含纯合成数据，只读。
- 运行工作副本：`data/demo_crm/runtime/mock_crm.json`，必须加入 `.gitignore`。
- 交易和审计记录保留 7 天。
- 不得包含真实手机号格式、真实身份信息或真实凭证。
- 只读种子文件可以包含公开静态 `DEMO_TOKEN_` 测试映射，但不得包含任何真实或生产凭证。

### 6.2 应用日志

允许记录：

- `request_id`、`conversation_id` 和 `anonymous_user_id`。
- Intent、Agent 类型、Tool 名称、耗时、成功/失败和标准错误码。
- `transaction_id` 和 `idempotency_key` 只能记录不可逆哈希。

禁止记录：

- 完整用户消息、Prompt 和原始 Tool payload。
- Mock CRM `user_id`、`mobile_alias`、精确账户值和交易结果快照。
- Token、Authorization Header、API Key、数据库密码和其他 Secret。

保留期为 7 天。

### 6.3 Redis

一般会话状态允许保存：

- `anonymous_user_id`、`conversation_id`、Intent、Agent 类型。
- 去除精确账户值和禁止字段后的最近对话摘要。
- 不含交易明细的临时业务状态。

一般会话状态 TTL 最长为 24 小时。

办理确认上下文属于受信任执行层的专用数据，允许保存：

- 内部 Mock CRM `user_id`、`confirmation_id`、`tool_name`。
- 标准化目标参数、价格、关键条件、参数哈希和确认状态。
- `created_at`、`presented_at`、`confirmed_at` 和 `expires_at`。

确认上下文 TTL 为 5 分钟，进入 `consumed`、`cancelled` 或 `expired` 后不得延长。不得保存 Token、Authorization Header、原始用户消息或完整 Prompt。

### 6.4 ChromaDB Episodic Memory

允许保存：

- 与会话级匿名标识关联的非敏感业务需求摘要。
- 用户主动表达的预算、预计流量和预计通话偏好。
- 不含账户值、交易和身份字段的脱敏对话摘要。

禁止保存：

- 原始完整聊天记录。
- Mock CRM `user_id`、`mobile_alias` 和任何手机号。
- 精确余额、剩余量、套餐订购关系、确认上下文和交易记录。
- 身份、支付、地址、真实客户资料和任何 Secret。

保留期最长为 30 天。`BusinessAgent` 首期继续禁用 `user_profile` 更新，不得用 Episodic Memory 绕过该限制建立账户画像。

### 6.5 测试集与评测报告

- 测试问题、账户、Tool 结果和期望响应必须完全合成，并使用 `demo_` / `DEMO_` 标识。
- 禁止从运行日志、真实聊天、真实账单或外部业务系统复制测试数据。
- 进入测试或报告前必须执行禁止字段和秘密扫描。
- 版本化测试夹具可以随仓库保留；运行时评测结果和临时报告最长保留 30 天。
- 报告只能包含匿名 ID、Intent、Agent 结果、脱敏 Tool 状态和评分，不包含精确账户值、交易 ID 或原始 Tool payload。

## 7. 禁止持久化和禁止输出

除第 6.1 节授权的纯合成 Mock CRM 数据外，禁止在非授权存储中持久化：

- 精确账户值、手机号、证件、银行卡、支付、地址、订单和账单信息。
- 除只读种子文件中获批的公开静态 `DEMO_TOKEN_` 映射外，任何 Mock Token 副本、真实或生产 Token、API Key、Secret Key、Authorization Header 和数据库密码。
- 原始用户消息、完整 Prompt、内部异常堆栈和原始 Tool payload。

禁止 Agent 或确定性响应层输出：

- 属于其他用户的任何账户或交易数据。
- Token、Secret、内部数据库结构、异常堆栈和未授权内部规则。
- Tool 未返回成功时的伪成功、伪扣费或伪业务状态。

“内部数据库结构”不包括经过授权并转换为用户可理解文本的当前套餐、余额、剩余量和交易状态。

## 8. Tool 写操作与两轮确认

所有自动写操作必须执行：

```text
首轮用户提出办理请求
  → 验证身份、目标、价格和业务条件
  → prepare_business_operation 生成 5 分钟确认上下文
  → 确定性确认模板向用户复述业务、价格和关键条件
  → 停止本轮并等待用户下一轮明确确认
  → 执行层验证用户、会话、Tool、参数、价格和确认状态
  → 调用写 Tool
  → 数据原子更新成功
  → 确定性响应层返回 Demo 办理结果
```

- 用户首轮即使包含“购买”“帮我办理”或“确认购买”，也不得直接调用写 Tool。
- 确认问题必须由准备 Tool 的结构化字段通过确定性模板生成，外部 LLM不得改变业务名称、价格或关键条件。
- 用户拒绝、表达含糊、改变条件或确认超时，不得执行写 Tool。
- LLM、Agent 和响应模板均不得直接修改 Mock CRM。
- Tool 返回 `unknown`、`manual_review`、超时或异常时不得表示成功，必须按合同查询原交易或进入 Demo 人工介入路径。

## 9. 功能完整性与安全验收

进入实现后，以下验收项必须全部通过：

- 已认证用户能够正常查询精确余额、当前套餐、剩余流量和剩余通话分钟。
- 精确账户查询结果由确定性响应层正确返回，但不会出现在外部 LLM 输入、日志、Redis 一般会话数据、ChromaDB 或评测报告中。
- 未认证、Token 无效或账户不匹配时，不返回任何个人账户数据。
- 首轮办理表达只产生确认问题；下一轮匹配确认后才调用一次写 Tool。
- 套餐变更、流量包购买、语音包购买、增值业务开通、套餐退订和 Demo 充值分别覆盖成功、余额不足、拒绝确认、确认过期、参数变化、幂等重放、Tool 失败和未知状态。
- 确定性确认模板中的产品、价格、生效和退款条件与准备 Tool 返回值一致。
- Tool 成功前不返回办理成功；Tool 失败时不发生部分扣费、部分发放或状态漂移。
- 敏感字段与 Secret 扫描覆盖 Prompt、日志、Redis、ChromaDB、测试夹具和评测输出。
- 安全过滤或响应模板发生故障时采用安全失败路径，同时保留明确、可理解的用户提示和人工介入能力。

不得仅以单元测试替代端到端验证。写操作上线前必须验证“HTTP 请求 → Mock Token → Agent/路由 → 准备确认 → 下一轮确认 → 写 Tool → Mock CRM → 确定性响应”的完整链路。

## 10. 后续扩展与变更控制

如果未来接入真实运营商系统、真实用户数据或真实支付，必须停止沿用本政策并重新评估：

- 合法性与用户授权。
- 数据访问、最小权限和身份认证。
- 传输与静态加密。
- 审计、保留、删除和数据主体权利。
- 外部 LLM、第三方 API 和跨境数据边界。
- 生产事故响应和人工工单闭环。

改变外部 LLM allowlist、精确账户响应路径、保留期、Mock Token 边界或允许的数据来源时，必须提升文档版本并由 Owner/Approver 重新批准。
