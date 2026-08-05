# EchoMind 中国移动智能客服项目接手文档

> 本文用于把当前项目交接给新的开发对话或新的 Agent。它记录的是一个可复核的时间点，不替代项目根目录中的 `PLAYBOOK.md`。

| 字段 | 值 |
| --- | --- |
| 状态 | CONFIRMED |
| 文档版本 | 1.0 |
| 快照日期 | 2026-08-05（Asia/Shanghai） |
| Owner | Zhuoxi Li |
| Approved By | Zhuoxi Li |
| 审批权限 | Zhuoxi Li 是本项目唯一且最高审核人，其明确同意即可生效 |
| 快照基准提交 | `2e3b64eec0ae0cbff6d808cab627b6ac51d8dfa6` |
| 快照分支 | `codex/business-agent-demo` |
| 项目路径 | `/Users/lizhuoxi/项目/EchoMind` |

## 1. 新 Agent 必须先遵守的规则

1. 开始任何开发前，必须完整阅读项目根目录的 `PLAYBOOK.md`，然后完整阅读本文。
2. `PLAYBOOK.md` 是唯一的开发流程与安全操作手册；本文只提供当前项目快照、已确认业务事实和下一步建议。
3. 不得用历史对话、旧报告或本文替代当前源码检查。接手后必须先运行 `git status`，并检查相关源码、契约和测试。
4. 当前未确认其他业务 Agent、业务边界、Intent、知识材料和真实系统接口。不得自行猜测或提前实现。
5. 不得读取、复制、展示或提交 `.env` 中的密钥和配置值。环境变量名称以 `.env.example` 为准。
6. 不得在文档、日志、测试输出或对话中泄露 Mock Token、用户隐私、精确账户数据等受保护信息。
7. 不得删除或重置本地 CRM 运行时数据、Chroma 数据、Redis 数据、评估基线或用户改动，除非 Zhuoxi Li 明确授权。
8. 任何真实系统接入、真实收费、真实身份认证或生产发布都需要新的明确授权和技术契约。

## 2. 审批、分支和 PR 规则

### 2.1 审批事实

- Zhuoxi Li 是 Owner、Approved By，也是本项目唯一且最高审核人。
- 后续不需要 Mentor 审批，也不得把 Mentor 审批当作开发阻塞条件。
- 需要业务确认、技术合同确认、破坏性操作授权或范围扩展时，直接向 Zhuoxi Li 说明所需信息、格式和建议存放位置。
- Zhuoxi Li 的明确同意即可作为项目审批结论，但仍必须遵守 `PLAYBOOK.md` 的安全检查、验证和证据要求。

### 2.2 Git 当前状态

- 当前分支：`codex/business-agent-demo`
- 当前提交：`2e3b64e feat: implement BusinessAgent mobile service demo`
- 上游分支：`origin/codex/business-agent-demo`
- 远程仓库：`https://github.com/zl488ZhuoxiLi/EchoMind-China-Mobile-Agent.git`
- 基准 `main` 在本快照时为：`ea7678f consolidate development documentation into playbook`
- 在创建本文之前，工作区是干净的；本文自身会成为基准提交之后的新改动。

### 2.3 PR 当前状态与后续规则

- 按创建本文前 Zhuoxi Li 提供的 GitHub 截图，已有一个处于 Open 状态的 PR：`#1 feat: implement BusinessAgent mobile service demo`；新 Agent 接手时必须重新核验实时状态。
- 该 PR 是当前 BusinessAgent 阶段成果的已有交付记录；是否合并或关闭，由 Zhuoxi Li 决定。
- 后续开发不再默认要求创建 PR。
- 后续可以采用 Zhuoxi Li 批准的直接提交/推送流程，但不得擅自把开发分支合并或推送到 `main`。
- 每次提交前仍需给出变更范围和验证结果；是否提交、合并、推送由 Zhuoxi Li 明确决定。

## 3. 项目总体状态

EchoMind 仍保留 FastAPI、Multi-Agent、RAG、Redis、ChromaDB、Skills、Monitor 和 Evaluation 的整体架构。当前已完成第一个中国移动业务垂直切片：把原 `BillingAgent` 替换为确定性的 `BusinessAgent` Demo，并建立 Mock Token、Mock CRM、业务 Tool、二次确认、确定性账户响应和自动化测试。

当前不是生产系统，不能连接或代表真实中国移动业务系统。除 BusinessAgent 外，GeneralAgent 和 TechnicalAgent 仍保留原型/演示性质。

## 4. 已确认的 BusinessAgent 业务契约

### 4.1 身份和命名

| 项目 | 已确认值 |
| --- | --- |
| 稳定 `agent_id` | `business_agent` |
| `AgentType` 外部值 | `business_agent` |
| Python class | `BusinessAgent` |
| 原 `BillingAgent` | 已替换，不保留外部调用兼容层 |
| 现有 billing 外部调用方 | 已确认没有 |
| Demo 登录状态来源 | Mock Token |

### 4.2 人设和职责

BusinessAgent 是耐心、专业、温和的移动业务顾问，负责移动套餐、流量包、语音包、增值业务、账户信息和有限的宽带信息服务。它应先理解需求、清楚解释价格与规则、不强推业务，并在任何写操作前取得单独一轮明确确认。

### 4.3 当前 13 个确定性 Intent

- `business_account_query`
- `business_plan_query`
- `business_plan_recommendation`
- `business_plan_change`
- `business_plan_unsubscribe`
- `business_product_query`
- `business_data_pack_purchase`
- `business_voice_pack_purchase`
- `business_vas_activation`
- `business_account_recharge`
- `business_transaction_status`
- `business_broadband_query`
- `business_manual_service`

Business Intent 先通过确定性分类器识别，不依赖外部 LLM 决定业务写入路径。

### 4.4 第一阶段允许自动执行的写操作

- 套餐变更与 Demo 套餐退订处理
- 流量包购买
- 语音包购买
- 增值业务开通
- Demo 账户充值
- 用户套餐状态更新
- 用户业务订购关系更新
- 用户余额扣减

所有写操作必须满足：

```text
用户第一次表达办理意愿
→ Agent 返回包含业务名称和价格的确认问题
→ 等待用户在下一轮明确确认
→ Tool 调用
→ 数据更新成功
→ 返回确定性办理结果
```

即使用户第一轮已经说“确认购买”“帮我办理”或“就这个套餐”，也只能生成待确认记录和确认问题，不能同一轮执行写 Tool。只有下一条独立用户消息明确确认后才能执行。

当前认可的确认表达包括但不限于：

- 确认办理
- 确定购买
- 帮我办理
- 就这个套餐
- 按这个方案办理
- 开通这个业务
- 购买

确认必须绑定登录用户、会话、目标 Tool、参数摘要、价格和状态，不能跨用户、跨会话或跨商品复用。当前确认有效期为 5 分钟。

### 4.5 必须人工处理的业务

- 销户
- 新开户
- 停机保号
- 国际漫游
- 宽带移机
- 身份认证相关业务
- 账单争议、退款等高风险业务
- Tool 异常或账户状态异常后的人工介入
- 用户主动要求人工、投诉或连续表达不满意

当前 Demo 只返回人工处理标记和说明，不会创建真实工单，也不能承诺人工已经受理完成。

### 4.6 禁止行为

- 虚构不存在的套餐、价格、优惠或政策。
- Tool 未返回成功时宣称已经开户、销号、扣费、改套餐或开通业务。
- 不通过 Tool 直接修改 CRM 数据。
- 查询未登录用户的个人账户数据。
- 泄露 Token、手机号码、余额、交易详情或其他个人数据。
- 把 Demo 数据或 Demo 结果描述成真实中国移动在售产品或真实办理结果。

## 5. 当前实现架构

### 5.1 Business 特殊请求路径

Business 请求当前采用独立的确定性路径：

```text
POST /chat
→ 校验可选 Bearer Mock Token
→ 确定性 Business Intent 识别
→ BusinessAgent / BusinessService
→ 读取或准备业务 Tool
→ 必要时等待第二轮确认
→ 确定性结果返回
```

这一条路径在通用 Memory、用户画像、RAG、Query Rewrite 和外部 LLM 之前完成路由。Business 响应的 `knowledge_used` 为 `false`，Business 消息当前不写入通用 Memory 或用户画像。

这样做是为了确保账户余额、资源余量、交易状态、价格和办理结果不会被 LLM 改写。架构依据见：

- `docs/architecture/ADR/0002-deterministic-protected-account-response.md`
- `docs/architecture/ADR/0003-business-deterministic-path-before-memory-rag.md`

GeneralAgent 和 TechnicalAgent 仍继续走原有的 Memory/RAG/LLM 原型路径。

### 5.2 认证与授权

- `/chat` 支持 Bearer Mock Token。
- Token 解析出的用户身份是账户数据权限的唯一依据。
- 已登录 Token 与请求体中的 `user_id` 不一致时返回 HTTP 403。
- Mock Token 支持撤销和过期状态。
- 未登录用户可查询公开套餐/产品说明，但不能查询个人账户或执行写操作。
- Mock Token 仅用于本地 Demo，不是生产认证方案。

不要把原始 Token 值写入本文、日志、评估报告或测试说明。原始 Demo Token 只允许保留在受控的种子数据中。

### 5.3 Mock CRM

主要文件：

- `mcp/mock_crm.py`
- `data/demo_crm/mock_crm.json`
- `data/demo_crm/runtime/mock_crm.json`（运行时文件，Git 忽略）

种子数据为纯合成 Demo 数据，目前包含 4 个套餐、7 个产品、3 个 Demo 用户和 4 个 Mock Token 映射。套餐定价和资源配置按国内通信业务常见逻辑设计，但不代表真实中国移动在售资费。

运行时 CRM 文件目前已经包含本地 E2E 验证产生的合成交易和账户变化。不要静默删除或覆盖它。如需恢复到种子状态，必须先向 Zhuoxi Li 说明影响并获得明确授权。

Mock CRM 当前实现了进程内锁、原子 JSON 替换和幂等交易记录。交易记录保留期为 7 天。

### 5.4 已注册的 8 个 Business Tool

- `get_account_summary`
- `list_plans`
- `list_products`
- `prepare_business_operation`
- `change_plan`
- `purchase_product`
- `recharge_account`
- `get_transaction_status`

Tool 契约版本为 1.5，详情以 `docs/business/MOCK_CRM_TOOL_CONTRACT.md` 为准。

### 5.5 超时、异常和并发保护

- 写 Tool 使用幂等键，重试前先查询已有交易。
- Tool 超时会写入非重试型 `unknown / TOOL_TIMEOUT` 交易状态，不改变余额、套餐、资源或订购关系。
- 未预期异常会写入 `manual_review / INTERNAL_ERROR` 状态。
- 晚到的后台线程会检查同一幂等交易，不允许在超时兜底后继续提交数据。
- 超时/异常响应包含确定性的 Demo 参考交易号，用户可继续查询状态。
- 并发购买同一增值业务时，只允许一次成功订购和扣费。

## 6. 业务数据和知识材料状态

### 6.1 Demo 产品目录

来源文件：`docs/business/sources/custom_demo/DEMO_CATALOG_SOURCE.md`

- 状态：CONFIRMED
- 版本：1.1
- 所有套餐与产品都是自定义 Demo 数据。
- 文档列出了中国移动公开页面作为定价合理性参考，但没有把公开页面内容直接等同为 Demo 产品合同。
- 后续修改价格、资源、适用范围或产品状态时，应同时更新种子数据、来源说明、Tool 契约和相关测试。

### 6.2 RAG 知识库

- 当前知识统计接口显示 6 个知识分块。
- BusinessAgent 目前不使用 RAG 返回精确业务数据。
- General/Technical 的原型知识路径仍存在。
- 不得把未确认的中国移动材料直接导入正式知识库。新材料至少需要来源、版本、适用范围和公开使用权限信息。

### 6.3 Skills

当前 `/skills` 可发现 3 个 Skill：

- Business：`skills/business_service/SKILL.md`
- General：原型 Skill
- Technical：原型 Skill

旧的 `skills/billing_support/SKILL.md` 已删除。Business Skill 只描述已确认的 Demo 行为，不能用于扩展未批准业务。

## 7. 关键文档索引

接手时应按任务需要阅读以下文件；涉及其主题的开发不得只阅读本文：

- `PLAYBOOK.md`：唯一开发流程与安全手册，必须首先完整阅读。
- `docs/business/AGENT_CATALOG.md`：Agent 身份、边界和业务治理，当前版本 0.8。
- `docs/business/INTENT_CATALOG.md`：Business Intent 契约，当前版本 1.2。
- `docs/business/MOCK_CRM_TOOL_CONTRACT.md`：Tool 输入、输出、错误、确认和幂等契约，当前版本 1.5。
- `docs/business/sources/custom_demo/DEMO_CATALOG_SOURCE.md`：Demo 套餐与产品来源，当前版本 1.1。
- `docs/security/PERSONAL_DATA_POLICY.md`：个人数据和日志规则，当前版本 1.1。
- `docs/architecture/ADR/0001-business-agent-identity-and-mock-auth.md`：Agent 身份与 Mock Auth 决策。
- `docs/architecture/ADR/0002-deterministic-protected-account-response.md`：受保护精确数据的确定性响应决策。
- `docs/architecture/ADR/0003-business-deterministic-path-before-memory-rag.md`：Business 路由顺序决策。

以上业务、安全与架构文档当前状态均为 CONFIRMED，Owner/Approved By 均为 Zhuoxi Li。

## 8. 环境和服务配置

### 8.1 主要运行环境

- Python：3.12 slim 容器
- API：FastAPI + Uvicorn，容器端口 8000
- Nginx：主机端口 80
- Redis：主机端口 6379
- ChromaDB：主机端口 8001，容器端口 8000
- Prometheus：主机端口 9090
- 本地开发通过 Docker Compose 运行

### 8.2 `.env.example` 中的配置组

当前环境变量名称包括：

- 应用：`APP_NAME`、`APP_ENV`、`LOG_LEVEL`、`API_HOST`、`API_PORT`
- LLM：`ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`
- Redis：`REDIS_URL`、`REDIS_PASSWORD`
- Mock CRM：`MOCK_CRM_SEED_PATH`、`MOCK_CRM_DATA_PATH`
- Chroma：`CHROMA_HOST`、`CHROMA_PORT`、`CHROMA_PERSIST_DIRECTORY`
- 监控：`PROMETHEUS_PORT`、`ANOMALY_DETECTION_THRESHOLD`
- Evaluation：`EVAL_BASELINE_PATH`
- Skills：`ECHOMIND_SKILLS_DIR`、`ECHOMIND_SKILLS_MAX_PROMPT_CHARS`
- 安全占位：`SECRET_KEY`、`JWT_SECRET_KEY`
- Grafana：`GRAFANA_USER`、`GRAFANA_PASSWORD`
- 功能开关：以 `.env.example` 当前内容为准

本地 `.env` 已存在，但任何 Agent 都不得读取后把值复制到输出、提交或新文档中。Docker Compose 会覆盖部分容器内路径和服务地址，并挂载 Chroma、Evaluation、Mock CRM runtime、Skills 和日志目录。

### 8.3 本快照时的容器状态

以下服务均已验证为 healthy：

- `echomind-app`
- `echomind-chromadb`
- `echomind-nginx`
- `echomind-prometheus`
- `echomind-redis`

已验证接口：

- `/health` 返回 `status=ok`，Agent 包含 `general_0`、`technical_0`、`business_agent_0`。
- `/skills` 返回 3 个 Skill。
- `/knowledge/stats` 返回 6 个知识分块。

Nginx 健康检查已改用 `127.0.0.1`，当前正常。

## 9. 验证和测试状态

### 9.1 自动化测试

测试文件：

- `tests/test_business_flow.py`
- `tests/test_business_intents.py`

默认测试命令：

```bash
docker compose run --rm --no-deps \
  -v "/Users/lizhuoxi/项目/EchoMind:/app" \
  echomind python -m unittest discover -s tests -v
```

本快照验证结果：共发现 26 个测试，25 个通过，1 个按设计跳过。跳过项是需要独立 Redis 测试库的集成测试。

Redis 集成测试命令：

```bash
docker compose run --rm --no-deps \
  -e ECHOMIND_TEST_REDIS_URL=redis://:echomind123@redis:6379/15 \
  -v "/Users/lizhuoxi/项目/EchoMind:/app" \
  echomind python -m unittest \
  tests.test_business_flow.BusinessRedisFlowTests -v
```

该测试已单独验证通过。它使用 Redis DB 15、唯一测试键，并只清理自己创建的键。不得为运行测试而执行全库 `FLUSHDB` 或 `FLUSHALL`。

### 9.2 已验证的 API 行为

- 未登录用户可以查询公开套餐和产品。
- 已登录用户可以获得确定性的精确账户摘要。
- 写业务第一轮只返回价格和确认问题，不修改 CRM。
- 下一轮明确确认后，Tool 只执行一次。
- 确认重放被阻止。
- 取消确认不产生写入。
- Token 用户与请求 `user_id` 不一致时返回 403。
- Business 响应不使用 RAG，日志中没有外部 Query Rewrite。
- Tool 超时、异常、重复请求和并发订购保护已有自动化覆盖。

### 9.3 Evaluation

- 已同步 13 个 Business 默认 Intent 用例。
- 独立基线文件：`data/eval/business_agent_baseline.json`。
- 原有 `data/eval/baseline.json` 保留，未覆盖。
- Evaluation 报告元数据使用哈希，不保存原始问题、回答或会话 ID。
- 尚未运行需要付费外部模型的完整 LLM-as-Judge 评估。
- 运行付费或耗时的外部评估前，必须向 Zhuoxi Li 说明预计调用范围、成本和输出位置，并取得明确批准。

文档类改动通常不需要重跑全部业务测试，但至少应执行 `git diff --check` 并复核链接、状态和事实。任何代码或契约变更应按风险运行对应单元测试、集成测试和必要的 E2E。

## 10. 已知问题、限制和发布阻塞项

### 10.1 Chroma 实际连接问题

虽然 `echomind-chromadb` 容器健康，但应用启动日志显示知识库连接远程 Chroma 服务失败，随后回退到应用容器内的 `/app/data/chroma` 本地持久化目录。日志同时出现 Chroma PostHog telemetry 参数异常。

因此，当前“Chroma 容器健康”不等于“应用正在使用该 Chroma 服务”。这是下一阶段最优先的 Stage 0A 基础设施核对项。BusinessAgent 因为不走 RAG，所以本地业务 Demo 没被它阻塞。

处理该问题时：

- 先做只读诊断，确认客户端模式、Host/Port、版本和数据目录。
- 不得直接删除、重建或迁移现有 Chroma 索引。
- 如果要从本地持久化改为远程服务，必须说明数据兼容与回退方案。
- 修复目标应是“应用明确使用已批准的单一模式”，不能只消除日志而不验证实际读写位置。

### 10.2 其他已知限制

- 没有真实中国移动 CRM、认证、支付、工单或计费系统接入。
- Mock Token 是静态 Demo 认证，不能用于生产。
- 人工转接只返回标记，不创建真实工单。
- CORS 当前开放，管理/写接口缺少生产级鉴权。
- Memory 异步路径中仍有同步 Redis 调用，可能阻塞事件循环。
- Skill/监控日志可能包含消息片段，真实数据接入前必须进一步隐私收敛。
- GeneralAgent 和 TechnicalAgent 仍是通用演示能力。
- 尚未进行完整外部 LLM 质量评估、压力测试或生产安全审计。
- 当前成果可以作为本地 Demo 和下一阶段开发基线，不能宣称生产就绪。

### 10.3 `PLAYBOOK.md` 中需要同步的“当前事实”

`PLAYBOOK.md` 是唯一流程手册，不应被本文覆盖。但其部分“当前事实”仍描述 BusinessAgent 改造前的状态，至少包括：

- 0.3：仍描述所有请求先经过 Memory/RAG/Intent，而当前 Business 路径是已记录 ADR 的例外。
- 0.4：仍只列 General/Technical/Billing 和单一知识 Tool，未反映 BusinessAgent 与 8 个 Business Tool。
- 9.1：仍写没有自动化测试，而当前已有 26 个 Business 测试。

新 Agent 不得据此恢复旧架构。下一次文档维护应在 Zhuoxi Li 同意后，只更新这些已过时的“当前事实”，保留流程、安全规则和历史背景；修改前应先对照源码、ADR、契约和实际测试结果。

## 11. 下一步开发流程

### 11.1 新对话接手检查

新 Agent 的第一轮只做确认和检查：

1. 完整阅读 `PLAYBOOK.md`。
2. 完整阅读本文。
3. 运行 `git status --short --branch`，确认有没有用户未提交改动。
4. 运行 `git log -1`、`git branch -vv`，确认当前分支、提交和上游。
5. 确认现有 PR #1 是否已被 Zhuoxi Li 合并或关闭，不得只依赖本文快照。
6. 查看与当前任务直接相关的 ADR、业务契约、源码和测试。
7. 向 Zhuoxi Li 简要报告实际状态、发现的偏差和准备执行的下一小步。

### 11.2 建议的立即下一步：文档事实对齐

先处理一个小而独立的文档任务：根据第 10.3 节核对并更新 `PLAYBOOK.md` 的过时“当前事实”。只做事实同步，不改流程原则、不扩展业务范围。完成后执行 `git diff --check`，并由 Zhuoxi Li 审核。

### 11.3 建议的下一项技术任务：完成 Stage 0A Chroma 核验

文档事实对齐后，建议按 `PLAYBOOK.md` 的基础设施核验流程处理 Chroma 实际连接问题。建议范围：

1. 只读检查 `mcp/knowledge_base.py`、`memory/conversation_memory.py`、`api/main.py`、Docker Compose 和 `.env.example`。
2. 收集应用启动日志和 Chroma 健康/版本信息，不读取或展示秘密。
3. 明确当前客户端为什么回退本地目录，并提出最小修复方案。
4. 在变更前向 Zhuoxi Li 说明是否涉及索引格式、数据目录、依赖版本或 ADR。
5. 实现后验证应用实际连接目标、知识写入/查询、重启持久化和失败回退。
6. 不得删除现有索引；如需迁移或重建，另行请求批准。

### 11.4 Chroma 之后的可选方向

完成 Stage 0A 后，由 Zhuoxi Li 选择下一条路线，不得由 Agent 自行扩展：

**路线 A：新增另一个业务 Agent 垂直切片**

必须先收集并确认稳定 `agent_id`、Python class、Intent、允许/禁止范围、登录和数据权限、写操作确认、Tool 契约、知识来源、隐私规则和人工转接条件。资料不全时先提供模板和存放目录，不得猜测实现。

**路线 B：进入 Stage 6 工程化加固**

可选项包括管理接口鉴权/CORS、异步 Redis、日志隐私、监控、Evaluation 和负载验证。每一项应作为独立小任务，分别定义风险、验收和回滚。

在另一个单 Agent 垂直切片稳定之前，不建议提前进入复杂的多 Agent 协作编排。没有新的明确授权时，也不得接入真实系统。

## 12. 新对话可直接使用的启动指令

将下面内容作为新对话的第一条消息即可：

```text
你现在接手 EchoMind 中国移动智能客服改造项目。

项目路径：
/Users/lizhuoxi/项目/EchoMind

开始任何开发前，必须完整阅读：
1. /Users/lizhuoxi/项目/EchoMind/PLAYBOOK.md
2. /Users/lizhuoxi/项目/EchoMind/docs/operations/PROJECT_HANDOFF.md

PLAYBOOK.md 是唯一开发流程与安全手册，PROJECT_HANDOFF.md 是 2026-08-05 的项目状态快照。不要依赖历史对话代替当前源码检查。

Owner 和唯一最高审核人是 Zhuoxi Li。后续不需要 Mentor 审批，也不默认要求创建 PR；提交、合并或推送仍需按我的明确指示执行。

先不要修改文件。请先：
- 检查 git status、当前分支、HEAD 和上游；
- 核对接手文档与当前源码是否一致；
- 检查 PR #1 当前是否已经合并或关闭；
- 简要报告当前进度、工作区状态、已知风险；
- 说明按 PLAYBOOK 建议执行的下一小步。

不得猜测或提前实现尚未确认的新 Agent、Intent、业务数据、知识材料或真实系统接口。需要我提供信息时，请明确说明格式、内容和建议存放目录。
```

## 13. 接手完成的判断标准

新 Agent 只有在完成以下事项后，才算真正接手：

- 已完整阅读 `PLAYBOOK.md` 和本文。
- 已用 Git 和源码确认实际状态，而不是只复述本文。
- 已识别用户未提交改动、分支/PR 变化和运行环境差异。
- 已理解 Business 写操作的严格两轮确认与确定性响应边界。
- 已理解当前 Mock 数据、真实系统、个人数据和人工业务边界。
- 已向 Zhuoxi Li 报告下一小步及其验证方法。
- 未在未经批准的情况下修改、删除、迁移、提交、合并或推送任何内容。
