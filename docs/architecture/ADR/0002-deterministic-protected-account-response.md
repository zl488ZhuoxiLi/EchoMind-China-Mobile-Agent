# ADR-0002: Deterministic Response Path for Protected Demo Account Data

Status: CONFIRMED
Decision State: ACCEPTED
Owner: Zhuoxi Li
Approved By: Zhuoxi Li
Approval Date: 2026-08-05
Source References: `docs/security/PERSONAL_DATA_POLICY.md` version 1.1; `docs/business/MOCK_CRM_TOOL_CONTRACT.md` version 1.5
Last Updated: 2026-08-05
Version: 1.1

## Problem

`BusinessAgent` 必须向已认证用户正常返回精确余额、剩余流量、剩余通话和 Demo 交易结果，但外部 LLM不应接收这些受保护账户字段。简单删除精确字段会破坏账户查询能力，直接把完整 Tool payload 交给外部 LLM又违反已确认的数据边界。

## Decision

采用受信任的确定性响应路径：

1. 执行层验证 Mock Token，并以 Token 映射的 `user_id` 校验账户归属。
2. Tool 正常查询或更新 Mock CRM，保留完整的结构化结果。
3. 编排层将结果拆分为 `llm_visible` 和 `deterministic_response_only`。
4. 外部 LLM只接收显式 allowlist 中的公开或匿名字段。
5. 确定性响应层通过固定模板把精确账户字段和 Demo 交易结果返回给当前已认证用户。
6. 确定性响应层发生异常时安全失败，不得把原始 Tool payload 发送给外部 LLM作为 fallback。

办理确认问题同样使用确定性模板。`prepare_business_operation` 返回的业务、价格、生效和退款条件必须原样进入确认问题；外部 LLM不得修改交易字段。

## Functional Boundary

该决策是数据流隔离，不是功能降级：

- 已认证用户仍可查询精确余额、当前套餐、剩余流量和剩余通话。
- 用户仍可完成已批准的套餐变更、流量包购买、语音包购买、增值业务开通、套餐退订和 Demo 充值。
- 外部 LLM仍可使用公开产品资料、用户主动表达的需求和匿名业务状态进行解释与推荐。
- Tool 成功、失败、未知和人工介入结果必须被准确展示。

## Consequences

- Tool 响应模型或编排层需要显式区分 LLM 可见字段与受保护字段。
- 账户查询和交易结果不能完全依赖 LLM自由生成，需要固定模板和结构化响应测试。
- Prompt、Tool 消息、日志、Redis 一般会话数据、ChromaDB 和评测输出需要相应的字段过滤和泄漏测试。
- 前端或 `/chat` 响应可以继续返回自然语言，但精确字段必须来自确定性模板而非 LLM复述。

## Implementation Preconditions

- Mock CRM 数据必须完全合成。
- 确定性响应模板、字段 allowlist 和错误路径必须先有测试再接入写操作。
- 两轮确认状态机、幂等、事务和账户归属校验必须按已确认 Tool Contract 实现。
- 必须有端到端用例证明功能结果完整且受保护字段未进入外部 LLM或非授权存储。

## Rollback

不得回滚为“把完整 Tool payload 发送给外部 LLM”。如果确定性响应路径无法工作，应关闭相关个人账户入口并返回安全失败，修复后再恢复；不得以泄露受保护字段换取功能可用性。
