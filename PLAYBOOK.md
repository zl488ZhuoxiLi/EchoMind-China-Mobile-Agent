# EchoMind 业务改造开发手册

> 作用：EchoMind 唯一的开发流程与安全操作手册。  
> 目标：让新的开发者或 AI Agent 在离开原对话后，也能快速理解当前项目，并以最小、兼容、可验证的方式继续改造。  
> 当前方向：在保留 FastAPI、多 Agent、RAG、Memory、Skills、Monitor 和 Evaluation 基础结构的前提下，将现有演示客服改造成目标业务系统。  
> 当前业务状态：具体 Agent、业务规则和数据边界尚未全部确认。未确认内容不得写入生产 Prompt、路由、知识库或高风险逻辑。

---

## 0. 新 Agent 接手指南

### 0.1 开始工作的正确顺序

接到任何开发任务后，先按顺序执行：

1. 完整阅读 `PLAYBOOK.md`。
2. 运行 `git status --short`，保护用户已有改动。
3. 阅读任务涉及的完整源码、调用方、被调用方和 API 模型。
4. 阅读对应的 `CONFIRMED` 业务、安全或架构文档。
5. 确认本次任务属于哪个阶段、哪个 Agent 垂直切片。
6. 写清目标、非目标、风险、验证方法和回滚方式。
7. 做最小修改并完成针对性验证。

不得仅根据聊天记忆、历史报告、文件名或注释猜测当前行为。

### 0.2 当前项目快速地图

| 位置 | 当前职责 |
|---|---|
| `api/main.py` | FastAPI 入口、组件装配、HTTP 接口、`/chat` 主链 |
| `agents/agent_orchestrator.py` | Agent class、System Prompt、路由、并行协作、fallback |
| `core/intent_recognizer.py` | 单主 Intent、置信度、紧急度和实体提取 |
| `core/skill_loader.py` | Skill 发现、匹配、加载和 Prompt 注入 |
| `skills/*/SKILL.md` | 按 Agent 和关键词生效的业务处理规则 |
| `mcp/knowledge_base.py` | ChromaDB `knowledge_base` 的导入、切片和检索 |
| `mcp/tool_manager.py` | Tool 注册、校验、缓存、超时、熔断、fallback、查询改写和重排 |
| `memory/conversation_memory.py` | Redis 工作记忆、ChromaDB 情景记忆和用户画像 |
| `monitor/performance_monitor.py` | Agent/Tool 运行统计、告警和路由 penalty |
| `evaluation/evaluator.py` | Intent 指标、真实 Agent 评测、LLM-as-Judge 和基线比较 |
| `Dockerfile`、`docker-compose.yml` | 运行时和服务编排 |
| `.env.example`、`requirements.txt` | 环境变量与 Python 依赖的权威来源 |

### 0.3 当前请求链路

当前源码中的 `/chat` 顺序是：

```text
POST /chat
  ↓
读取 Redis / Chroma Memory
  ↓
共享 Knowledge RAG 检索
  ↓
IntentRecognizer
  ↓
AgentOrchestrator
  ↓
一个或多个 Agent
  ↓
固定 System Prompt + 动态 Skill + 共享 Memory/RAG Context
  ↓
LLM
  ↓
写回会话 Memory，异步更新用户画像
  ↓
ChatResponse
```

这是“当前默认架构基线”，不是永远不可调整的目标架构。业务隔离或准确性需要改变 RAG 顺序、知识过滤或 Tool 权限时，先形成简短 ADR，再做最小兼容调整。

### 0.4 当前起点与已知限制

下列是开始业务改造前必须重新验证的起点，不得把“存在实现”误认为“已经生产可用”：

- 当前可执行 Agent 是 General、Technical、Billing；它们仍是演示客服语义。
- Intent 只返回一个主意图；技术与账单复合请求由 Orchestrator 关键词补充判断。
- 所有 Agent 当前共享同一个 `knowledge_base`，没有 Agent/领域 metadata 过滤。
- RAG 当前发生在 Intent 和 Agent 选择之前，一个或多个 Agent 接收同一批知识上下文。
- 当前只注册 `knowledge_search`，Agent 没有真实业务办理 Tool。
- Escalation 只有状态标记，没有真实工单或人工通知闭环。
- 当前没有自动化 `tests/`，`requirements.txt` 也没有 `pytest`。
- 管理/写入类接口当前没有鉴权，CORS 当前允许所有来源；不适合直接公开部署。
- Memory 的 async 路径使用同步 Redis Client，可能阻塞事件循环。
- Skill 日志可能包含用户消息片段，真实业务接入前需要脱敏策略。
- Compose 必须确认应用容器实际使用 `chromadb:8000`，不能只因 Chroma 容器健康就认为应用已连接它。
- Monitor 的 success 主要表示调用未抛异常，不等同于回答正确或业务成功。
- 当前评测依赖外部 LLM，且 `/eval/run` 会写基线文件。

已知限制是否阻塞开发或发布，由阶段 0A 的验证结果决定。修复后应同步更新本节，不能永久保留过期结论。

---

## 1. 权威来源与文档规则

### 1.1 不同事实由谁负责

| 事实类型 | 权威来源 |
|---|---|
| 开发步骤、安全门禁、完成标准 | `PLAYBOOK.md` |
| 当前运行行为 | 当前源码和配置 |
| Python 版本 | `Dockerfile` |
| Python 依赖和版本 | `requirements.txt` |
| 容器、端口、网络、卷 | `docker-compose.yml`、`Dockerfile` |
| 环境变量名称 | `.env.example` |
| HTTP 合同 | `api/main.py` 中的路由和 Pydantic 模型 |
| 目标业务行为 | `docs/business/` 中 `CONFIRMED` 的内容 |
| 数据和安全要求 | 已确认的公司要求、法律要求、授权文件和安全文档 |
| 已批准架构变化 | `docs/architecture/ADR/` 中已接受的 ADR |

`PLAYBOOK.md` 不能覆盖法律、公司安全制度、数据授权或 Mentor 的明确要求。

### 1.2 文档确认状态

业务、安全和架构文档建议在开头记录：

```text
Status: DRAFT | CONFIRMED | DEPRECATED
Owner:
Approved By:
Approval Date:
Source References:
Last Updated:
Version:
```

规则：

- `DRAFT` 和 `UNKNOWN` 可用于讨论、样例和测试设计，不能直接进入生产 Prompt、路由、知识库或高风险逻辑。
- `CONFIRMED` 必须由有权限的业务、安全或技术负责人确认；负责人不明确时继续保持 `DRAFT`。
- 当前源码与目标业务文档不一致时，源码代表“现在如何运行”，`CONFIRMED` 文档代表“应该改成什么”。
- 历史分析报告、聊天记录和普通注释只提供线索，不是权威来源。
- 精确数值和易变清单，例如端口、Intent 权重、TTL、Agent ID、Skill 名称和路由映射，保留在源码或配置中，不在多份文档重复维护。

无法确认时统一写：

```text
UNKNOWN
需要进一步确认
```

---

## 2. 当前架构边界

默认在现有模块内扩展，不把相同逻辑复制到其他位置：

```text
HTTP 组装          → api/main.py
Agent 与路由       → agents/agent_orchestrator.py
Intent 与实体      → core/intent_recognizer.py
Skill 加载         → core/skill_loader.py
Tool 可靠执行      → mcp/tool_manager.py
Knowledge/RAG      → mcp/knowledge_base.py
会话与用户记忆    → memory/conversation_memory.py
在线监控           → monitor/performance_monitor.py
离线评测           → evaluation/evaluator.py
```

保持概念隔离：

```text
System Prompt = Agent 的长期身份、目标和责任边界
Skill         = 某类场景的处理流程、SOP 和禁止事项
Tool          = 查询或改变真实业务状态的执行能力
Knowledge     = 可追溯的业务事实
Memory        = 会话历史和用户画像
```

保持存储隔离：

```text
knowledge_base = 企业知识
episodic       = 历史会话摘要
user_profile   = 用户画像
Redis          = 短期工作记忆
```

以下变化必须先写简短 ADR：

- 改变 `/chat` 的核心执行顺序。
- 共享 collection 与多 collection 的选择。
- 引入知识 metadata filter 或两阶段检索。
- 改变公开 API 合同或稳定 Agent ID。
- 引入真实高风险 Tool 或新的持久化存储。
- 改变用户数据保存期限、用途或权限。

ADR 只需说明问题、候选方案、决定、理由、兼容影响和回滚方式，不追求形式复杂。

---

## 3. 最小工程原则

- 一次任务只解决一个明确问题或一个 Agent 垂直切片。
- 优先局部、兼容、可回滚的修改，不顺带重构或升级依赖。
- 不为未来假设批量创建目录、空文件、抽象类或配置层。
- 没有真实 Tool 接口时，MVP 可以只做知识问答、流程引导和人工升级。
- Mock Tool 必须明确标记为模拟，不能声称真实查询、办理或退款成功。
- 不新增依赖，除非现有依赖无法完成任务且用户明确批准。
- 不在无关任务中升级依赖、模型或镜像。
- 保持 async/fallback/超时/熔断等现有可靠性行为。
- 不静默破坏 API 字段、状态码、Agent ID、监控标签或评测基线。
- 不自动 commit、push、deploy、调用高成本外部服务或操作真实数据。

---

## 4. 最小文档与数据结构

### 4.1 第一批业务文档

业务明确后，第一批最多创建：

```text
docs/
├── business/
│   ├── BUSINESS_OVERVIEW.md
│   ├── USER_SCENARIOS.md
│   ├── AGENT_CATALOG.md
│   ├── AGENT_BOUNDARY_MATRIX.md
│   ├── INTENT_CATALOG.md
│   └── ESCALATION_POLICY.md
└── security/
    └── SECURITY_BASELINE.md
```

先合并表达，出现真实维护冲突时再拆分：

- 业务术语可先放在 `BUSINESS_OVERVIEW.md`。
- Agent 的输出风格和详细契约可先放在 `AGENT_CATALOG.md`。
- 实体字段可先放在 `INTENT_CATALOG.md`。
- 隐私、密钥和公开仓库策略可先合并进 `SECURITY_BASELINE.md`。

### 4.2 按需创建的工程资产

只有进入相应工作后才创建：

```text
docs/architecture/ADR/       # 出现真实架构决策时
data/knowledge/sources/      # 拿到允许进入 RAG 的材料时
data/knowledge/manifests/    # 开始正式知识版本管理时
tests/                       # 开始建立自动化测试时
evaluation/cases/            # 开始积累回归用例时
tools/                       # 拿到真实业务接口时
scripts/                     # 出现可复用导入/验证操作时
```

不为保持目录树外观创建空目录或 `.gitkeep`。

### 4.3 知识材料规则

允许提交仓库：

- 公开官网信息。
- 自己编写的模拟数据。
- 明确授权公开的脱敏材料。

禁止提交仓库：

- 真实手机号、账单、地址、身份信息和工单。
- 内部系统地址、账号、Token、API Key 和证书私钥。
- 未公开资费、内部指标、培训材料和真实故障记录。
- 网络拓扑或带保密标识的文件。

敏感内部资料优先放在仓库之外的受控位置，不默认建立仓库内 `private_sources/`。无法确认仓库可见性时，按公开仓库处理。

正式知识 manifest 第一版建议包含：

```text
document_id
title
version
domain
region
effective_date
expiry_date
source
confidentiality
status
applicable_agents
checksum
```

`user_type`、`channel`、`contract_period`、`applicable_intents` 等字段只在真实业务存在差异时增加。

运行和生成数据不得提交：

```text
.env
data/chroma/
data/knowledge/processed/
evaluation/reports/
logs/
真实用户数据
```

只在对应目录真实创建时更新 `.gitignore`。

---

## 5. 所有任务的统一执行协议

### 5.1 开始前

```text
[ ] 确认任务所属阶段和 Agent 切片。
[ ] 阅读相关源码和 CONFIRMED 文档。
[ ] 运行 git status，识别已有改动。
[ ] 记录当前基线、已知失败和未确认问题。
[ ] 确认是否涉及 API、数据、权限、费用或外部系统。
```

### 5.2 实施前

必须写清：

- 目标与非目标。
- 业务依据与确认状态。
- 受影响调用链和文件。
- 当前行为与目标行为。
- 正常、边界、失败和 fallback。
- 测试、验收和回滚方式。

### 5.3 风险等级

| 等级 | 例子 | 最低验证 |
|---|---|---|
| 低 | 文档、注释 | 内容、链接、diff |
| 中 | Prompt、Skill、Intent 样例 | 单元测试或确定性用例、回归样例 |
| 高 | 路由、RAG 过滤、Tool、Memory | 单元 + 集成 + 失败路径 + API 冒烟 |
| 极高 | API 破坏、数据迁移、权限、生产配置 | 用户确认、兼容方案、回滚演练、端到端验收 |

### 5.4 实施约束

- 不覆盖、还原或格式化任务外的用户改动。
- 不吞异常；记录必要上下文并保留既有 fallback。
- 不在 FastAPI 请求链引入阻塞网络调用。
- 不直接编辑 ChromaDB SQLite/HNSW 文件。
- 不把 Knowledge、Skill、Memory 和 Tool 混为一体。
- 不在日志、异常、测试、Prompt 或文档中泄露敏感信息。
- 注释主要解释为什么需要某逻辑、并发、fallback 或边界。

### 5.5 验证顺序

```text
语法和静态检查
  ↓
目标模块测试
  ↓
单元测试
  ↓
集成测试
  ↓
必要时真实端到端评测
  ↓
Docker/API 冒烟
  ↓
git diff 与敏感信息检查
```

没有相应测试时必须明确报告，不能用“代码看起来正确”代替验证。

### 5.6 完成报告

必须说明：

1. 修改文件和行为。
2. 执行的验证及结果。
3. 未执行的验证及原因。
4. API、数据、安全和兼容风险。
5. 回滚方式。
6. 剩余 `UNKNOWN`。

---

## 6. 推荐开发路线

### 阶段 0A：运行基线、安全与 Git

目标：知道当前项目能否运行，以及哪些问题阻塞开发或发布。

操作：

- 检查依赖、环境变量、Compose、Docker 和 Git 状态。
- 验证 `/health`、`/docs` 和当前 `/chat` 最小链路。
- 确认应用实际连接的 Redis 和 ChromaDB。
- 验证 Knowledge、Skills、Memory、Monitor 和 Evaluation 当前状态。
- 记录已知问题、阻塞级别、预计处理阶段和验证方式。
- 建立最小 `SECURITY_BASELINE.md`。
- 确认远端仓库可见性；无法确认时按公开仓库处理。

说明：基线记录可以放在当前任务报告中；只有 Mentor、审计或长期协作确实需要时，才创建 `docs/operations/BASELINE_STATUS.md`。

门禁：

- 当前运行状态有证据。
- 开发阻塞与发布阻塞已区分。
- 不存在密钥、真实用户数据或未知敏感材料误提交风险。

### 阶段 0B：统一业务建模

目标：先统一定义所有 Agent 的总体边界，再开始代码改造。

最少确认：

- 产品目标、用户类型和核心场景。
- Agent 清单；每个 Agent 的中文显示名称、稳定 `agent_id`、计划使用的 Python class 名称和 `AgentType`。
- 每个 Agent 的核心使命、服务对象、负责业务、非负责业务和用户期望结果。
- 每个 Agent 必须收集的信息、澄清问题、回答格式、禁止事项和人工升级条件。
- 每个 Agent 允许使用的 Skill、Knowledge、现有 Tool 和未来可能需要的 Tool；未来 Tool 只能记录需求，不能写成已经具备的能力。
- Agent 重叠区域、转交、拒绝和人工升级。
- Intent 草案、实体字段和真实用户问法。
- 允许使用的知识、数据和外部能力。
- 回答风格和成功标准。

`AGENT_BOUNDARY_MATRIX.md` 至少要能回答：

- 每个业务场景由谁主责。
- 是否需要协作 Agent，以及协作 Agent 只负责哪一部分。
- 哪些 Agent 明确不应处理该场景。
- 多个 Agent 都可能处理时，主责和优先级如何确定。
- 哪些条件必须拒绝、转交或升级人工。

门禁：

- Agent 数量和主边界不再冲突。
- 第一个垂直切片的范围已确认。
- 未确认内容没有进入运行逻辑。

### 阶段 1：必要架构决策

只处理会影响多个 Agent 的真实决策，例如：

- RAG 在 Intent 前还是后。
- 共享 collection、metadata filter 或多 collection。
- 稳定 Agent ID 是否需要兼容 alias。
- 多 Agent 结果如何合并。
- Tool 和数据权限如何隔离。

没有真实分歧就不创建 ADR，不为了完成阶段而制造决策。

### 阶段 2–4：按 Agent 垂直切片

按业务优先级逐个完成 Agent。每个切片必须同时处理：

```text
Agent 契约和稳定 ID
  ↓
System Prompt
  ↓
Intent、实体和样例
  ↓
Intent-Agent 路由
  ↓
Skill
  ↓
允许访问的 Knowledge
  ↓
可选 Tool
  ↓
单 Agent 测试和评测
  ↓
保持整个项目可运行
```

不得在完成新 Prompt 后，长期保留与之冲突的旧 Intent、Skill 和电商知识。

每完成一个切片都要小步提交，确认 main 或当前稳定分支仍可运行，再进入下一个 Agent。

### 阶段 5：多 Agent 协作

在单 Agent 闭环稳定后再实现：

- 多 Intent 或复合问题表示。
- 并行还是串行。
- 主 Agent 和协作 Agent。
- 响应合并与冲突处理。
- 部分失败、超时和 fallback。
- 重复 RAG/Tool 调用控制。
- 升级到人工的真实语义。

### 阶段 6：增强能力

按真实需求选择，不要求全部实现：

- Memory 和用户画像。
- 真实业务 Tool。
- RAG 改写、重排和知识版本治理。
- 更完整的 Evaluation。
- Monitor、告警和路由反馈。
- CI 和自动化回归。

没有真实业务接口时，Tool 不阻塞 MVP；没有用户画像需求时，不扩大个人数据保存范围。

### 阶段 7：全链路验收与发布

发布前确认：

```text
[ ] 业务、安全和架构决策已确认。
[ ] Prompt、Intent、路由、Skill、Knowledge 和评测语义一致。
[ ] API 兼容或迁移方案已确认。
[ ] 正常、边界、失败和安全测试通过。
[ ] Docker 服务和依赖连接已验证。
[ ] 知识版本和数据来源可追溯。
[ ] 日志、Prompt 和测试中没有敏感数据。
[ ] 监控和人工升级方式明确。
[ ] 回滚路径有效。
```

---

## 7. Agent 垂直切片验收模板

每个 Agent 至少确认：

### 契约

- 中文显示名称、稳定 `agent_id`、Python class 名称和 `AgentType`。
- 核心使命、服务对象、负责业务、非负责业务和用户期望结果。
- 必需实体、必须收集的信息和信息不足时的澄清问题。
- 回答格式、输出风格和成功标准。
- 禁止事项、禁止承诺、拒绝条件和人工升级条件。
- 允许的 Skill、Knowledge、现有 Tool 和未来 Tool 需求。

### Prompt

System Prompt 只包含稳定内容：Agent 身份、核心使命、负责与不负责范围、真实性与安全约束、基本回复原则和人工升级原则。

不要把易变 FAQ、完整业务政策、价格、详细 SOP、密钥或尚未实现的 Tool 能力写进 System Prompt；前四类内容应根据性质进入 Skill 或 Knowledge。

### Intent 与路由

- 每个 Intent 有定义、正例、反例和易混淆例。
- 低置信度、高风险和缺少实体时有明确处理。
- 检查旧 ID 对 API、Skill、Monitor、Evaluation、日志和外部调用方的影响。
- 没有外部调用方时可以尽早使用正确稳定 ID；存在调用方时设计 alias 或迁移方案。

### Skill

- 来自已确认 SOP。
- Agent 范围和触发条件明确。
- 明确业务处理步骤、必收信息、场景分支、回复格式、禁止事项和升级条件。
- 测试应命中、误命中、多 Skill 和长度上限。
- 保留当前 reload 机制。

### Knowledge

- 来源、版本、地区、生效/失效时间和敏感等级明确。
- Agent 访问范围符合边界。
- 无答案、过期、跨域和提示注入场景经过测试。

### Tool

- 无真实接口时可以不存在。
- Mock 必须明确标记，不得声称实际成功。
- 真实 Tool 定义输入、输出、权限、幂等、超时、fallback 和审计。
- 写操作必须在执行层校验权限，并按风险要求用户确认或人工审核。

### 行为用例

每个 Agent 都应覆盖以下类别，具体数量按业务复杂度和风险确定，不把固定条数作为机械门禁：

- 应该由该 Agent 处理的问题。
- 不应该由该 Agent 处理的问题。
- 信息不足、需要澄清的问题。
- 必须转交或升级人工的问题。
- 越权、安全、提示注入或诱导虚构后台操作的问题。
- 容易与其他 Agent 混淆的边界问题。

高风险 Agent 应增加相应反例和失败用例。测试必须验证 Agent 不越权、不虚构未执行的 Tool 操作，并在正确条件下拒绝、转交或升级。

### 切片完成标准

- 新 Agent 不依赖冲突的旧 Prompt、Intent、Skill 或知识。
- 单 Agent 正常、非职责、信息不足、越权、混淆、失败和升级用例通过。
- 公开 API 和稳定 ID 的变化已处理。
- 项目整体仍可启动和回滚。

---

## 8. 安全与数据治理底线

阶段 0 必须明确每类数据是否允许进入：

```text
Git 仓库
外部 LLM 请求
Prompt
应用日志
Redis
ChromaDB knowledge_base
ChromaDB episodic
ChromaDB user_profile
测试集和评测报告
```

默认规则：

- 密钥、密码和 Token 不进入 Git、Prompt、日志或 Skill。
- 真实手机号、地址、账单、身份和工单不得作为公开样例。
- 发送外部 LLM 前必须确认数据授权和脱敏要求。
- Knowledge、会话记忆和用户画像不能混用 collection。
- 用户画像字段必须有业务用途、保存期限、删除方式和可读 Agent。
- 高风险 Tool 权限不能只靠 Prompt 控制。
- 无法判断环境是本地、测试还是生产时，不执行写数据、迁移或高成本评测。

具体数据分类和保存期限：

```text
UNKNOWN
需要由用户、Mentor 或有权限的业务/安全负责人确认
```

---

## 9. 测试与 LLM 调用规则

### 9.1 当前测试事实

- 当前仓库没有自动化 `tests/`。
- 当前 `requirements.txt` 没有 `pytest`。
- 未批准新依赖前使用标准库 `unittest` 或项目现有评测入口。

### 9.2 测试分层

| 类型 | 目标 | 是否允许 Mock |
|---|---|---|
| Unit | 单个函数、匹配、路由和校验 | 允许隔离外部服务 |
| Integration | Agent 切片、RAG、Memory、Tool 组合 | 可 Mock 外部依赖，但不能绕过被测组合 |
| E2E | 真实 `/chat` 和编排行为 | 必须经过真实 `AgentOrchestrator.run()`；外部服务是否模拟需明确记录 |

### 9.3 测试数据隔离

建立集成测试前必须确保：

- Redis 使用独立 DB、前缀或测试实例。
- ChromaDB 使用临时目录或测试 collection。
- `EVAL_BASELINE_PATH` 使用测试临时文件。
- 测试用户使用 `test_`/`eval_` 前缀。
- 用户画像更新被关闭、隔离或在测试后清理。
- 不读取、覆盖或删除真实用户数据和生产基线。

### 9.4 外部 LLM

采用两种最小模式即可：

```text
快速模式：不调用或只抽样调用外部 LLM，用于日常开发
完整模式：经用户确认后调用真实 LLM，用于关键回归和发布验收
```

调用前记录模型、Base URL 类型、Prompt/Knowledge/评测集版本、用例数量和预期费用范围。设置合理超时和失败处理，不因外部 LLM 失败把整个评测误判为通过。

评测结果有波动时，使用固定用例重复验证；关键安全和权限规则必须用确定性断言，不能只依赖 LLM-as-Judge。

---

## 10. Git、提交与回滚

- 开始前运行 `git status --short`。
- `main` 应尽量保持可运行。
- 高风险、多文件或跨模块切片建议使用 feature 分支；小型局部修改不强制建分支。
- 一个 commit 只表达一个清晰意图，避免把依赖升级、格式化和业务改造混在一起。
- 合并前运行对应测试、冒烟、敏感信息和 diff 检查。
- 第一次大规模业务改造前保留一个可识别的稳定 commit；正式发布时再使用版本 tag。
- AI 不自动 commit、push、deploy、删除真实数据或改写 Git 历史，除非用户明确要求。
- 回滚必须同时考虑代码、配置、Skills、Knowledge 索引和数据结构，不能只恢复一个 Python 文件。

---

## 11. 必须停止并请求确认

- Agent 数量、稳定 ID、职责或边界互相冲突。
- 业务材料仍是 `DRAFT`，但任务要求写入生产逻辑。
- 高风险操作缺少授权、确认或人工审核规则。
- 需要新增依赖、升级模型、改变数据库结构或破坏 API 兼容。
- 需要删除、覆盖、迁移真实数据或重建未知环境的索引。
- 无法判断环境是本地、测试还是生产。
- 相关文件包含无法安全合并的用户未提交改动。
- 知识来源、有效期、地区、权限或敏感等级不明。
- 测试失败涉及资金、隐私、权限、安全或跨用户数据泄漏。
- 真实 Tool 缺少接口合同、测试环境或执行层权限。
- 回滚路径不可用。

普通、可逆的内部实现选择可以在明确说明假设后采用最小方案；不得用合理假设代替关键业务授权。

---

## 12. 单次任务模板

```markdown
# 任务名称

## 阶段与 Agent 切片

## 目标 / 非目标

## 已确认依据
- 文件：
- 状态：
- Owner / Approver：
- Source：

## 当前行为 / 目标行为

## UNKNOWN

## 受影响调用链和文件

## API / 数据 / 安全 / 费用影响

## 实施步骤

## 测试
- 正常：
- 边界：
- 失败：
- 安全：
- 回归：

## 验收标准

## 回滚方式

## 最终结果
- 修改：
- 验证：
- 未验证：
- 风险：
```

---

## 13. Definition of Done

```text
[ ] 需求来自当前源码或已确认的业务/安全/架构依据。
[ ] 本次只完成一个明确问题或一个 Agent 垂直切片。
[ ] 没有额外重构、依赖升级或未来占位实现。
[ ] Prompt、Intent、路由、Skill、Knowledge 和测试语义一致。
[ ] API、稳定 ID、异步行为和 fallback 的兼容影响已处理。
[ ] 正常、边界、失败、安全和回归路径已验证或明确报告未验证。
[ ] 测试没有污染真实 Redis、ChromaDB、用户画像或评测基线。
[ ] 没有提交或输出密钥、日志、索引和真实用户数据。
[ ] git diff 已检查，没有覆盖无关改动。
[ ] 回滚方式明确。
[ ] 剩余 UNKNOWN 和发布阻塞已报告。
```

最终原则：

```text
先确认业务和安全边界
→ 再统一总体设计
→ 按 Agent 完成可运行的垂直切片
→ 最后开发协作和增强能力
→ 用真实证据决定是否发布
```
