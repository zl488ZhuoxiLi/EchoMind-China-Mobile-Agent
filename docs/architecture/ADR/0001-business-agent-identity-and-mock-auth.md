# ADR-0001: BusinessAgent Stable Identity and Mock Authentication Boundary

Status: CONFIRMED
Decision State: ACCEPTED
Owner: Zhuoxi Li
Approved By: Zhuoxi Li
Approval Date: 2026-08-05
Source References: `docs/business/AGENT_CATALOG.md` version 0.8; `docs/business/INTENT_CATALOG.md` version 1.2; `docs/business/MOCK_CRM_TOOL_CONTRACT.md` version 1.5; `docs/security/PERSONAL_DATA_POLICY.md` version 1.1
Last Updated: 2026-08-05
Version: 1.4

## Problem

EchoMind 当前使用 `BillingAgent`、`AgentType.BILLING` 和对外值 `billing` 表示演示性账单/退款客服。已确认的首个中国移动业务切片是“移动业务办理与套餐服务”，其责任范围、身份和稳定 ID 都与现有 Billing 演示语义不一致。

同时，个人账户查询和业务办理需要可由执行层校验的 Demo 身份来源，不能只依赖 `user_id` 请求字段、Prompt 或用户自述。

## Evidence from Current Source

`billing` 当前同时影响：

- `AgentType`、`BillingAgent` class、Agent pool 和 Intent 路由。
- `/chat` 响应中的 `agent_type`。
- Billing Skill 的 `agents` 匹配值。
- Monitor 统计和路由 penalty key。
- Evaluation 用例和已有基线。

Owner 确认现有 `billing` 没有外部调用方。

## Considered Options

### Option A: 保留 `BillingAgent`，扩大其责任

优点：对当前代码变更小。

缺点：`billing` 无法稳定表达套餐、流量、语音、增值业务和账户办理的整体责任，会长期保留演示语义。

### Option B: 新增 `BusinessAgent` 并与 `BillingAgent` 并存

优点：可以渐进迁移。

缺点：当前没有已确认的独立账单 Agent 边界，并存会导致路由、Skill 和 Intent 重叠。

### Option C: 用 `BusinessAgent` 替换 `BillingAgent`

优点：使稳定 ID、class 和已确认业务范围一致，不保留无业务依据的并行 Agent。

缺点：必须同步迁移源码、Skill、Monitor、Evaluation 和 API 返回值。

## Decision

选择 Option C，并确定以下边界：

1. 稳定对外 `agent_id` 为 `business_agent`。
2. Python class 为 `BusinessAgent`。
3. `AgentType` 枚举成员为 `BUSINESS`，其对外值为 `business_agent`。
4. `BusinessAgent` 替换 `BillingAgent`，不长期保留 `billing` alias。
5. 迁移必须在同一个 Agent 垂直切片中同步处理 Agent pool、路由、Skill 匹配、Monitor 标签、Evaluation 用例/基线和 `/chat.agent_type`，不允许长期混用新旧语义。
6. 不长期保留 `IntentCategory.BILLING` 的演示语义；实现时按已确认 Intent Catalog 的 13 个 Business Intent 同步迁移分类、路由和评测。
7. Mock Token 通过 `Authorization: Bearer <mock_token>` 传入。该 Header 对公开咨询可选，对个人账户查询和写 Tool 必填。
8. Token 映射的 `user_id` 是执行层身份权威值。请求中的 `user_id` 与 Token 不一致时拒绝个人数据访问和写操作。
9. Mock Token 只用于公开仓库中的 Demo 数据，不得声称或复用为生产认证方案。

## Compatibility Impact

- `/chat` 的 `agent_type` 将从 `billing` 变为 `business_agent`，是已确认的对外值变化。
- 当前无外部 `billing` 调用方，因此不设计长期 alias。
- 内部测试、评测基线、Skill 和 Monitor 标签必须与代码同步变更。
- `Authorization` Header 不影响公开咨询，但个人账户查询和写操作将在缺少或无效 Token 时被拒绝。
- 现有 `ChatRequest.user_id` 的去留和具体 HTTP 错误合同需在实现任务中明确，不得在无迁移说明时静默改变。

## Implementation Preconditions

- `docs/business/MOCK_CRM_TOOL_CONTRACT.md` 转为 `CONFIRMED`（已于 2026-08-05 满足）。
- `docs/business/INTENT_CATALOG.md` 确认第一个切片的 Intent、实体、易混淆边界和强制两轮确认协议（已于 2026-08-05 满足）。
- 个人数据在外部 LLM、日志、Redis、ChromaDB、测试集和评测报告中的规则已在 `docs/security/PERSONAL_DATA_POLICY.md` version 1.1 中确认（已于 2026-08-05 满足）。
- 精确账户数据使用 `docs/architecture/ADR/0002-deterministic-protected-account-response.md` 的确定性响应路径（已于 2026-08-05 满足）。
- 评测基线更新使用隔离路径，不覆盖未保护的生产或用户基线。

## Rollback

本 ADR 已实施。如需回滚，必须作为一个完整切片同时恢复：

- `BillingAgent`、`AgentType.BILLING` 和 Agent pool/路由。
- Billing Skill 适用标识。
- Monitor 标签和 Evaluation 用例/基线。
- `/chat.agent_type` 的 `billing` 响应。
- Mock Token Header 引入的个人数据和写 Tool 入口。

回滚不得只恢复 Agent class 而留下新旧 Skill、Intent、Monitor 或数据语义混用。
