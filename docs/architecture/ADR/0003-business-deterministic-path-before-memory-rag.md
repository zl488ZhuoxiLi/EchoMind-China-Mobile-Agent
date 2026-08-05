# ADR-0003: Business Deterministic Path Before General Memory and RAG

Status: CONFIRMED
Decision State: ACCEPTED
Owner: Zhuoxi Li
Approved By: Zhuoxi Li
Approval Date: 2026-08-05
Source References: `docs/business/AGENT_CATALOG.md` version 0.8; `docs/business/INTENT_CATALOG.md` version 1.2; `docs/business/MOCK_CRM_TOOL_CONTRACT.md` version 1.5; `docs/security/PERSONAL_DATA_POLICY.md` version 1.1; `docs/architecture/ADR/0002-deterministic-protected-account-response.md` version 1.1
Last Updated: 2026-08-05
Version: 1.0

## Problem

EchoMind 原通用 `/chat` 链路会在 Agent 路由前读取 Memory、使用外部 LLM改写查询并检索 RAG。BusinessAgent 的账户数据、交易确认和写操作已确认为受保护的确定性路径，尤其第二轮“确认购买”不能在命中 Redis 确认上下文前先交给外部模型。

## Decision

1. `/chat` 先验证可选 Mock Token，再使用确定性 Business Intent 规则和 Redis 待确认状态判断是否进入 Business 路径。
2. Business Intent、待确认轮和无有效上下文的独立确认短语均跳过通用 Memory、用户画像、LLM 查询改写和 RAG。
3. BusinessAgent 使用 Mock CRM Tool 和固定模板返回结果，不使用外部 LLM 生成资费、账户或交易内容。
4. Business 对话不写入通用会话 Memory 或 `user_profile`。两轮确认只使用专用 Redis key，并绑定 Token 用户、会话、Tool、标准化参数与价格。
5. 公开 Demo 套餐和产品查询也使用确定性 Business 路径，以保证展示内容只来自已确认的纯合成目录。

## Monitor Semantics

`BusinessAgent` 的 Agent success 表示确定性处理链路是否正常完成。未登录、余额不足、重复订购等预期业务拒绝不是 Agent 运行故障；它们仍由结构化业务结果表达。未捕获异常、Tool 超时或确定性响应层故障才应降低 Agent success 指标。

## Consequences

- 业务路径不使用通用长期记忆，后续如需业务 Memory，必须单独定义字段 allowlist、保留期和删除规则。
- 新增 Business Intent 时必须同步更新确定性分类、路由、Skill 和 Evaluation，否则可能错入通用 LLM/RAG 路径。
- `/chat.knowledge_used` 在 Business 路径始终为 `false`。

## Rollback

不得回滚为“先将 Business 消息发送给外部 LLM/Memory/RAG，再判断路由”。如确定性业务路径不可用，应关闭个人查询和写入入口并安全失败，保留公开咨询或人工介入提示。
