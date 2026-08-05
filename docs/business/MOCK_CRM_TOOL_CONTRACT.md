# Mock CRM and Tool Contract

Status: CONFIRMED
Owner: Zhuoxi Li
Approved By: Zhuoxi Li
Approval Date: 2026-08-05
Source References: `docs/business/AGENT_CATALOG.md` version 0.8; `docs/business/INTENT_CATALOG.md` version 1.2; `docs/security/PERSONAL_DATA_POLICY.md` version 1.1; `docs/business/sources/custom_demo/DEMO_CATALOG_SOURCE.md` version 1.1
Last Updated: 2026-08-05
Version: 1.5

> 本文档定义 `BusinessAgent` 首期 Demo 的 Mock CRM、Mock Token 和 Tool 技术合同。它已获批准，但不是真实中国移动接口合同，不得用于真实账户或声称具备生产能力。

## 1. 范围

### 包含

- Demo Mock Token 的传入与身份映射。
- Mock CRM 的用户、套餐、产品、订购关系和交易记录。
- 账户、套餐和产品查询 Tool。
- 套餐变更/退订、流量包/语音包购买、增值业务开通和账户充值 Tool。
- 用户确认、幂等、事务、错误和审计边界。

### 不包含

- 真实支付、身份认证或中国移动系统连接。
- 销户、新开户、停机保号、国际漫游和宽带移机的自动执行。
- 任意数据库字段修改 Tool。
- 生产级认证、授权或密钥管理。

## 2. 已确认技术边界

- Mock Token 通过 `Authorization: Bearer <mock_token>` 传入。
- Token 映射的 `user_id` 是身份权威值，不信任用户在请求文本中自述的身份。
- 无 Token 或 Token 无效时只允许公开咨询。
- Mock Token 是公开 Demo 标识，不是真实凭证，不得用于真实账户。
- 金额使用整数分，币种固定为 `CNY`。
- 流量使用整数 `MB`，通话时长使用整数分钟。
- 余额不足时拒绝购买，不允许负余额。
- 套餐变更立即生效，并包含退订。
- 变更套餐时立即扣除新套餐全额月费，不退还旧套餐费用。
- 退订套餐后 `current_plan_id` 设为 `null`，不退款。
- 充值只是 Demo 余额增加，不声称真实支付成功。
- 确认上下文有效期为 5 分钟，且所有写操作必须等待 Agent 发出确认问题后的下一轮用户明确确认。
- 所有写操作必须使用 `idempotency_key`。
- Mock CRM 交易和审计记录保留 7 天。
- `BusinessAgent` 首期禁用用户画像更新，不向 `user_profile` 写入业务或账户数据。
- 精确余额、剩余流量、剩余通话、Demo 移动标识和交易 ID 只进入确定性响应层，不发送给外部 LLM。

## 3. Mock CRM 文件

仓库内只读种子数据位置：

```text
data/demo_crm/mock_crm.json
```

只能包含自定义 Demo 数据，不得包含真实手机号、账单、地址、身份信息、工单或真实 Token。应用不得直接修改该仓库文件。

运行时工作副本位置：

```text
data/demo_crm/runtime/mock_crm.json
```

实现时通过 `MOCK_CRM_DATA_PATH` 配置运行时路径。工作副本不存在时，才从只读种子数据初始化；之后所有交易只写工作副本。真正创建该运行目录时必须同步将其加入 `.gitignore`，防止交易和测试数据进入 Git。

### 3.1 顶层结构

```json
{
  "schema_version": "1.1",
  "source_type": "synthetic_demo",
  "catalog_version": "1.0",
  "region_scope": "demo_not_region_specific",
  "users": [],
  "plans": [],
  "products": [],
  "subscriptions": [],
  "transactions": [],
  "mock_tokens": []
}
```

### 3.2 `users`

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `user_id` | string | 是 | 唯一，必须以 `demo_` 开头 |
| `mobile_alias` | string | 是 | 例如 `DEMO_MOBILE_001`，不使用真实号码格式 |
| `account_status` | enum | 是 | `active` 或 `abnormal` |
| `balance_cents` | integer | 是 | `>= 0` |
| `currency` | string | 是 | 固定 `CNY` |
| `current_plan_id` | string/null | 是 | 关联 `plans.plan_id`；退订后可为 `null` |
| `remaining_data_mb` | integer | 是 | `>= 0` |
| `remaining_voice_minutes` | integer | 是 | `>= 0` |
| `version` | integer | 是 | 乐观并发控制版本，每次写入加 1 |

### 3.3 `plans`

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `plan_id` | string | 是 | 唯一 Demo ID |
| `name` | string | 是 | 明确标记为 Demo 套餐 |
| `monthly_fee_cents` | integer | 是 | `>= 0` |
| `data_mb` | integer | 是 | `>= 0` |
| `voice_minutes` | integer | 是 | `>= 0` |
| `directional_benefits` | array[string] | 是 | 无则为空数组 |
| `description` | string | 是 | Demo 说明，不声称真实在售 |
| `status` | enum | 是 | `active` 或 `inactive` |

### 3.4 `products`

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `product_id` | string | 是 | 唯一 Demo ID |
| `product_type` | enum | 是 | `data_pack`、`voice_pack` 或 `vas` |
| `name` | string | 是 | Demo 产品名称 |
| `price_cents` | integer | 是 | `>= 0` |
| `quota_mb` | integer/null | 是 | 仅流量包使用 |
| `voice_minutes` | integer/null | 是 | 仅语音包使用 |
| `validity_days` | integer/null | 是 | 需要有效期的产品使用 |
| `billing_mode` | enum | 是 | `one_time` 或 `monthly_recurring` |
| `auto_renew` | boolean | 是 | 仅月度增值业务为 `true` |
| `effective_rule` | enum | 是 | 首期固定为 `immediate` |
| `repeat_purchase_allowed` | boolean | 是 | 资源包为 `true`；增值业务为 `false` |
| `description` | string | 是 | Demo 说明 |
| `status` | enum | 是 | `active` 或 `inactive` |

### 3.5 `subscriptions`

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `subscription_id` | string | 是 | 唯一 |
| `user_id` | string | 是 | 关联 `users.user_id` |
| `product_id` | string | 是 | 关联 `products.product_id` |
| `status` | enum | 是 | `active`、`cancelled` 或 `expired` |
| `started_at` | string | 是 | ISO 8601 UTC |
| `expires_at` | string/null | 是 | ISO 8601 UTC |
| `transaction_id` | string | 是 | 关联创建该订购关系的交易 |

### 3.6 `transactions`

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `transaction_id` | string | 是 | 唯一 |
| `user_id` | string | 是 | Token 映射用户 |
| `tool_name` | string | 是 | 执行写操作的 Tool |
| `operation` | string | 是 | 标准操作名 |
| `idempotency_key` | string | 是 | 在 `user_id + tool_name` 范围唯一 |
| `status` | enum | 是 | `pending`、`succeeded`、`failed`、`unknown` 或 `manual_review` |
| `amount_cents` | integer | 是 | 非负；非资金操作为 0 |
| `request_payload_hash` | string | 是 | 用于识别同 key 不同参数冲突 |
| `result_snapshot` | object/null | 是 | 幂等重放时返回的原结果 |
| `error_code` | string/null | 是 | 标准错误码 |
| `created_at` | string | 是 | ISO 8601 UTC |
| `completed_at` | string/null | 是 | ISO 8601 UTC |

### 3.7 `mock_tokens`

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `token_value` | string | 是 | 必须以 `DEMO_TOKEN_` 开头，不得复用真实凭证 |
| `user_id` | string | 是 | 关联 `users.user_id` |
| `status` | enum | 是 | `active` 或 `revoked` |
| `expires_at` | string/null | 是 | 静态 Demo Token 可为 `null` |

Mock Token 不记录到日志、Prompt、Memory、交易快照或错误响应。

`DEMO_TOKEN_` 是公开、本地、纯合成的测试身份标识，可以只存在于只读种子文件的 `mock_tokens` 映射中，不具备生产凭证安全性。任何真实或生产 Token 均禁止进入仓库。

## 4. 确认上下文

写 Tool 不得直接依赖 LLM 认为“用户已确认”。所有写操作采用不可跳过的两轮协议：

1. 用户首轮提出办理意愿后，执行层调用只读 `prepare_business_operation` 校验账户、目标、价格和业务状态，并生成确认上下文。
2. Agent 使用准备结果向用户复述具体业务、价格和关键条件，发出确认问题，然后停止本轮。
3. 用户下一轮明确确认后，执行层以确定性规则将匹配的上下文从 `awaiting_confirmation` 原子更新为 `confirmed`。
4. 写 Tool 只接受 `confirmed` 状态的上下文，开始事务时将其原子更新为 `consumed`。

用户首轮即使包含“购买”“帮我办理”或“确认购买”，也不能同时作为第二步确认。确认必须发生在 Agent 展示最终交易条件之后的新一轮消息中。

确认上下文存入 Redis 的 Demo 专用 key：

```text
demo_confirm:{user_id}:{confirmation_id}
```

字段：

| 字段 | 规则 |
|---|---|
| `confirmation_id` | 唯一 ID |
| `user_id` | 来自 Mock Token |
| `tool_name` | 预计执行的写 Tool |
| `business_intent` | 原始办理 Intent，用于确认轮继承正确的路由、监控和评测标签 |
| `normalized_params` | 去除自由文本后的确定性参数 |
| `params_hash` | 对参数计算的稳定哈希 |
| `summary` | 向用户告知的 Demo 业务、资费、生效时间和关键条件 |
| `confirmation_prompt` | 基于确定性业务字段生成、实际展示给用户的确认问题 |
| `created_at` | ISO 8601 UTC |
| `expires_at` | 创建后 5 分钟 |
| `presented_at` | Agent 向用户发出确认问题的时间；未展示时为 `null` |
| `confirmed_at` | 下一轮用户明确确认并通过绑定校验的时间；否则为 `null` |
| `status` | `awaiting_confirmation`、`confirmed`、`consumed`、`cancelled` 或 `expired` |

确认校验必须绑定 `user_id`、`confirmation_id`、`tool_name`、`params_hash` 和当前会话，并验证 `confirmed_at > presented_at`。不得把原始用户文本直接作为写 Tool 的“已确认”参数，也不得由 Agent 自行构造确认状态。

用户拒绝时将上下文标记为 `cancelled`。用户改变目标、金额、价格或关键条件时，原上下文必须标记为 `cancelled` 并重新准备。超过 5 分钟时标记为 `expired`，重新查询当前数据、重新展示条件并再次确认。写 Tool 只接受未过期且状态为 `confirmed` 的上下文；开始交易时原子更新为 `consumed`，防止重放。

## 5. Tool 通用合同

### 5.1 认证上下文

Tool handler 从受信任执行上下文读取：

```json
{
  "authenticated": true,
  "authenticated_user_id": "demo_user_001",
  "request_id": "...",
  "demo": true
}
```

写 Tool 不接受 Agent 在参数中传入的 `user_id`，避免横向越权。

### 5.2 统一响应

```json
{
  "success": true,
  "status": "succeeded",
  "tool_name": "change_plan",
  "transaction_id": "demo_tx_...",
  "data": {},
  "error": null,
  "demo": true
}
```

`status` 可为 `succeeded`、`failed`、`unknown` 或 `manual_review`。`unknown` 和 `manual_review` 不等于成功，Agent 必须明确转人工。

### 5.3 受保护 Tool 结果

Tool handler 必须对返回字段标注可见性或使用等价的类型隔离：

- `llm_visible`：只包含外部 LLM allowlist 中的公开业务字段、匿名业务状态和标准错误类型。
- `deterministic_response_only`：包含精确余额、剩余流量、剩余通话、`mobile_alias`、交易 ID 和其他受保护 Demo 账户字段。

编排层不得把完整 Tool 响应序列化进外部 LLM消息。确定性响应层在身份和账户归属校验后使用固定模板渲染 `deterministic_response_only`；渲染失败时安全失败，不得将原始 payload 转发给 LLM。

### 5.4 标准错误码

| 错误码 | 语义 | 是否允许 Agent 重试 |
|---|---|---|
| `AUTH_REQUIRED` | 缺少 Mock Token | 否 |
| `INVALID_TOKEN` | Token 无效或已撤销 | 否 |
| `FORBIDDEN` | 用户不匹配或越权 | 否 |
| `NOT_FOUND` | 账户、套餐或产品不存在 | 否 |
| `INVALID_ARGUMENT` | 参数非法 | 澄清后新请求 |
| `CONFIRMATION_REQUIRED` | 没有确认上下文 | 否 |
| `CONFIRMATION_NOT_PRESENTED` | 未向用户展示最终确认问题 | 否 |
| `CONFIRMATION_NOT_CONFIRMED` | 用户尚未在下一轮明确确认 | 否 |
| `CONFIRMATION_EXPIRED` | 确认超过 5 分钟 | 重新告知并确认 |
| `CONFIRMATION_MISMATCH` | 用户、Tool 或参数不匹配 | 否 |
| `INSUFFICIENT_BALANCE` | 余额不足 | 否 |
| `IDEMPOTENCY_CONFLICT` | 同 key 对应不同参数 | 否 |
| `INVALID_STATE` | 账户或业务状态不允许执行 | 否 |
| `MANUAL_REVIEW_REQUIRED` | 必须人工处理 | 否 |
| `TOOL_TIMEOUT` | 执行超时，结果未知 | 否，查询原交易或转人工 |
| `INTERNAL_ERROR` | 未预期异常 | 否，转人工 |

## 6. Tool 清单

### 6.1 `get_account_summary`

- 类型：只读。
- 认证：必须。
- 输入：无业务参数；用户来自执行上下文。
- 输出：`mobile_alias`、`account_status`、`balance_cents`、`currency`、`current_plan`、`remaining_data_mb`、`remaining_voice_minutes`。
- 可见性：`mobile_alias`、精确余额和精确剩余量属于 `deterministic_response_only`；外部 LLM只可接收当前套餐的公开字段和“余额充足/不足”等获批状态。
- fallback：只说明 Demo 账户查询暂不可用，不生成模拟余额或套餐。

### 6.2 `list_plans`

- 类型：只读，公开咨询可用。
- 输入：可选 `max_monthly_fee_cents`、`min_data_mb`、`min_voice_minutes`、`needs_directional_benefit`。
- 输出：匹配的 `active` Demo 套餐列表。
- 排序：月费升序，相同月费按 `plan_id` 升序，保证确定性。

### 6.3 `list_products`

- 类型：只读，公开咨询可用。
- 输入：可选 `product_type`、`max_price_cents`。
- 输出：匹配的 `active` Demo 产品列表。

### 6.4 `prepare_business_operation`

- 类型：只读预校验，会在 Redis 写入 5 分钟确认上下文。
- 认证：必须。
- 输入：`operation`、标准化的目标 ID 或金额。
- 行为：验证账户、产品/套餐、余额和业务状态，不改变 CRM 数据；创建状态为 `awaiting_confirmation` 的上下文。
- 输出：`confirmation_id`、`summary`、`confirmation_prompt`、`expires_at`、`normalized_params`。
- 约束：`confirmation_prompt` 必须由确定性模板生成并原样展示；外部 LLM不得修改业务名称、价格、生效或退款条件。展示后等待下一轮，不得在同一轮继续调用写 Tool。

### 6.5 `change_plan`

- 类型：写操作。
- 认证：必须。
- 输入：`action` (`change`/`unsubscribe`)、`target_plan_id` (变更时必填)、`quoted_price_cents`、`confirmation_id`、`idempotency_key`。`quoted_price_cents` 只能沿用准备 Tool 的结构化结果，用于价格绑定校验。
- 前置：确认问题已展示，且用户在下一轮对同一未过期上下文明确确认。
- 变更事务：验证新套餐和余额 → 扣除新套餐全额月费 → 立即更新 `current_plan_id` → 将剩余流量和通话重置为新套餐完整额度 → `version + 1` → 写入成功交易。原套餐和附加资源剩余量不结转，确认问题必须明确告知。
- 退订事务：将 `current_plan_id` 设为 `null`，并将剩余流量和通话置零 → `version + 1` → 写入成功交易；不退还已扣套餐费用。
- 变更失败必须整体回滚，不得只扣费不更新套餐。

### 6.6 `purchase_product`

- 类型：写操作。
- 认证：必须。
- 输入：`product_id`、`quoted_price_cents`、`confirmation_id`、`idempotency_key`。`quoted_price_cents` 只能沿用准备 Tool 的结构化结果。
- 前置：确认问题已展示，且用户在下一轮对同一未过期上下文明确确认。
- 事务：验证产品、重复购买规则和余额 → 扣减 `price_cents` → 增加流量/通话余量或创建增值业务订购关系 → `version + 1` → 写入成功交易。
- 首期资源包到期时间用于告知和交易快照，不运行定时过期扣减；增值业务创建月度续订关系，但首期不运行跨月自动扣费任务。
- 任一步失败必须整体回滚，不得只扣费不发放产品。

### 6.7 `recharge_account`

- 类型：写操作，仅 Demo。
- 认证：必须。
- 输入：`amount_cents` (`> 0`)、`quoted_price_cents`、`confirmation_id`、`idempotency_key`。两个金额必须与准备 Tool 结果完全一致。
- 前置：确认问题已展示，且用户在下一轮对同一未过期上下文明确确认。
- 事务：增加 `balance_cents` → `version + 1` → 写入 `DEMO_RECHARGE` 交易。
- 输出和用户文案必须含“Demo 模拟充值”，不得声称真实资金已到账。

### 6.8 `get_transaction_status`

- 类型：只读。
- 认证：必须。
- 输入：`transaction_id` 或 `tool_name + idempotency_key`。
- 越权保护：只返回当前 Token 用户的交易。

## 7. 幂等与事务

- 唯一键为 `authenticated_user_id + tool_name + idempotency_key`。
- 相同唯一键与相同 `request_payload_hash` 返回 `result_snapshot`，不重复执行。
- 相同唯一键但参数不同返回 `IDEMPOTENCY_CONFLICT`。
- 写操作必须在单个事务或等价原子临界区内完成余额、配额、套餐/订购关系和交易更新。
- 使用 `users.version` 检测并发写冲突。
- 已进入 `unknown` 或 `manual_review` 的交易不得由 Agent 重新执行。

## 8. 超时、重试与 fallback

- Mock 本地 Tool 超时上限为 3 秒。
- 只读 Tool 只可对明确的瞬时错误内部重试 1 次。
- 写 Tool 不做非幂等自动重试；超时时记录 `unknown`，通过原幂等 key 查询结果或转人工。
- 超时 fallback 必须先以原 `user_id + tool_name + idempotency_key + request_payload_hash` 查询已有交易：已成功则返回原结果；无最终结果时才原子记录 `unknown`。
- `unknown` 必须保存 `TOOL_TIMEOUT`、请求哈希和 Demo 参考交易编号，`completed_at = null`；不扣费、不发放资源、不改变套餐或订购关系。
- 未预期写 Tool 异常以相同幂等规则记录 `manual_review` 和 `INTERNAL_ERROR`，不得伪造成功结果。
- 后台执行如在超时后继续运行，必须在同一原子临界区内先检查幂等交易；已存在 `unknown` 或 `manual_review` 时不再扣费或办理。
- 只读 fallback 只能说明暂不可用，不得编造账户、套餐或产品数据。
- 写 Tool 不提供伪成功 fallback。

## 9. 审计与数据暴露

应用审计日志可包含：

- `request_id`、`conversation_id`、`anonymous_user_id`、`tool_name`、`operation`、`status`、`error_code`、时间戳和耗时。
- `transaction_id` 和 `idempotency_key` 只记录不可逆哈希，不记录原值。

禁止记录：

- Mock Token 原值。
- 完整用户消息或 LLM Prompt。
- 未脱敏的真实用户数据。
- Mock CRM `user_id`、`mobile_alias`、精确账户值和原始 Tool payload。

日志和 Mock CRM 交易记录保留 7 天。清理只能针对超过保留期的 Demo 运行时记录，不得删除仓库种子数据或其他存储中的数据。

## 10. 已批准的补充决策

1. 套餐立即变更时扣除新套餐全额月费，不对旧套餐按比例退费。
2. 套餐退订后 `current_plan_id = null`，不退款。
3. Mock CRM 交易和审计保留 7 天。
4. `BusinessAgent` 首期禁用用户画像更新。
5. 同一会话连续两轮明确表达不满时升级人工。确定性 Demo 关键词为“不满意”、“太差”、“没解决”、“还是不行”；“投诉”或明确要求人工时不等待两轮，立即升级。
6. 真实工单未实现时，复用现有 `ChatResponse.escalated = true`，并在响应文案中明确说明“当前为 Demo 人工介入标记，未创建真实工单”。
7. `data/demo_crm/mock_crm.json` 是只读种子数据；运行时写入 `data/demo_crm/runtime/mock_crm.json`，创建运行目录时必须同步加入 `.gitignore`。
8. 所有写操作统一执行“首轮准备并询问、下一轮明确确认、再调用写 Tool”的两轮协议；首轮用户表达不得直接授权写操作。
9. 精确账户数据和交易标识通过确定性响应层返回，不进入外部 LLM；该隔离不得导致账户查询或办理结果缺失。

## 11. 验收要求

- 无 Token、无效 Token、用户不匹配和横向越权用例均被拒绝。
- 用户首轮提出任何办理或预先确认表达时，只生成并展示确认问题，不调用写 Tool。
- 只有 Agent 展示最终条件后的下一轮明确确认，才能把匹配上下文更新为 `confirmed` 并调用一次写 Tool。
- 确认缺失、过期、用户不匹配、Tool 不匹配和参数不匹配用例均不执行写入。
- 用户拒绝、回复含糊或修改交易条件时不执行写入，旧确认上下文不可重放。
- 余额不足时不扣费、不发放产品。
- 相同幂等 key 重放不重复扣费或发放产品。
- 同 key 不同参数被拒绝。
- 并发购买不产生负余额或重复订购关系。
- 超时和未知结果不被表述为成功，且进入人工介入路径。
- 所有成功响应明确标记 `demo: true`。
- 日志、错误、Memory 和 Prompt 不包含 Mock Token 原值。
- 已认证账户查询能正确返回精确余额、剩余流量和剩余通话，但外部 LLM输入、日志、Redis 一般会话数据、ChromaDB 和评测报告均不含这些精确值。
- 确定性响应层故障时不泄露原始 Tool payload，并返回安全、可理解的失败或人工介入结果。
- 端到端测试覆盖 HTTP、Mock Token、路由、确认上下文、下一轮确认、写 Tool、Mock CRM 原子更新和确定性响应。
