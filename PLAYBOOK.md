# EchoMind 业务改造开发操作手册

> 用途：作为 EchoMind 唯一的开发流程与安全操作手册，指导后续 AI 与开发人员在不改变核心架构的前提下，安全、稳健地完成业务化改造。  
> 范围：Agent、System Prompt、Intent、路由、多 Agent 协作、Skills、Tools、知识库、RAG、Memory、用户画像、评测、监控和发布。  
> 当前状态：具体业务和 Agent 类型尚未确定。本手册只定义开发流程、文件职责与安全门禁，不预设业务事实。  
> 执行约束：只有用户明确指定某一阶段后，才能执行该阶段；不得因本手册提及未来目录而提前修改运行代码或批量创建空文件。

---

## 1. 事实来源与优先级

`PLAYBOOK.md` 是唯一的开发流程与安全规则来源。不要在其他文件中维护一套重复的开发阶段或完成标准。

不同类型的事实分别由以下来源负责：

1. 用户当前明确提出并确认的要求，以及 `docs/business/` 中状态为 `CONFIRMED` 的内容，定义目标业务行为。
2. 当前仓库中的真实源码、API 模型、配置与依赖，定义当前实现行为。
3. `docs/architecture/` 中经确认的技术设计与 ADR，定义已批准但可能尚未全部实现的架构决策。
4. 本 `PLAYBOOK.md` 定义从当前实现安全地到达目标行为的开发流程、验证门禁与停止条件。
5. 历史分析报告、示例数据和普通注释只提供背景，不是权威要求；与上述来源冲突时不得采用。

### 1.1 当前技术事实的权威来源

| 技术事实 | 权威来源 |
|---|---|
| Python 运行版本 | `Dockerfile` |
| Python 依赖及版本 | `requirements.txt` |
| 容器、镜像、端口、网络和卷 | `docker-compose.yml`、`Dockerfile` |
| 环境变量名称和示例 | `.env.example` |
| HTTP 路由、状态码、请求和响应结构 | `api/main.py` 中的路由与 Pydantic 模型 |
| Agent、Intent、Skill、Tool、RAG、Memory、Monitor 和 Evaluation 的当前行为 | 对应模块的当前源码 |
| 目标业务规则 | `docs/business/` 中状态为 `CONFIRMED` 的文档 |
| 已批准的架构变化 | `docs/architecture/ADR/` 中状态为已接受的 ADR |
| 开发步骤、安全门禁与完成标准 | `PLAYBOOK.md` |

技术事实使用规则：

- 不根据历史报告、聊天记录或记忆猜测依赖版本、环境变量、端口、API 字段或运行行为。
- 不在无关任务中升级依赖、模型或容器镜像。
- 当前源码与目标业务文档不一致时，源码代表“现在如何运行”，`CONFIRMED` 业务文档代表“应该改成什么”；必须设计最小、兼容、可验证的变更，不能把其中一方静默覆盖。
- 修改公开 API 前必须检查当前 Pydantic 模型、调用方和状态码；不得静默删除字段、改变语义或引入未经确认的全局响应包装。
- 精确数值和易变清单，例如 Intent 权重、Memory 阈值、TTL、端口、Agent 名称、Skill 名称和路由列表，应保留在源码或配置中，不在本手册复制维护。

冲突处理：

- 源码与历史分析报告冲突：以当前源码为准，标记报告已过期。
- 业务文档彼此冲突：停止实现，列出冲突并请求确认。
- 新需求与现有 API 合同冲突：不得静默破坏兼容性；先给出迁移方案。
- 新架构决策与现有模块边界冲突：先形成 ADR，经用户确认后再实施，并同步更新受影响的业务和架构文档。
- 无法从源码或已确认文档得出结论时，必须写：

```text
UNKNOWN
需要进一步确认
```

禁止根据示例 Agent、演示知识或模型常识猜测真实业务。

---

## 2. 不变的核心架构

除非用户明确授权架构调整，必须保留以下主链路：

```text
POST /chat
  ↓
api/main.py
  ↓
Memory Context + RAG Context
  ↓
IntentRecognizer
  ↓
AgentOrchestrator
  ↓
Agent + Dynamic Skills
  ↓
LLM
  ↓
Memory Update
  ↓
Monitoring / Evaluation
```

模块边界：

| 职责 | 当前文件 | 修改原则 |
|---|---|---|
| HTTP 接口与应用组装 | `api/main.py` | 不在这里堆积业务判断 |
| Agent 定义、选择与协作 | `agents/agent_orchestrator.py` | 保留兜底、性能路由和并行机制 |
| Intent 识别、置信度与实体 | `core/intent_recognizer.py` | 不退化为单纯关键词路由 |
| Skill 加载、匹配与注入 | `core/skill_loader.py` | 保留动态加载与 Agent 隔离 |
| Tool 注册与可靠执行 | `mcp/tool_manager.py` | 保留校验、超时、缓存、熔断与 fallback |
| RAG 存储与检索 | `mcp/knowledge_base.py` | 不从随机 Agent 代码直接访问 ChromaDB |
| 会话和用户记忆 | `memory/conversation_memory.py` | 不混入企业知识库 |
| 在线监控 | `monitor/performance_monitor.py` | 保留对路由评分的反馈关系 |
| 离线评测 | `evaluation/evaluator.py` | 端到端评测应走真实编排链路 |
| 业务操作规范 | `skills/*/SKILL.md` | 放处理流程，不充当事实知识库 |

必须保持三类数据逻辑隔离：

```text
knowledge_base = 企业业务事实
episodic       = 历史会话摘要
user_profile   = 用户画像与偏好
```

---

## 3. 目录演进原则

### 3.1 保留当前代码目录

现有 `api/`、`agents/`、`core/`、`skills/`、`mcp/`、`memory/`、`evaluation/`、`monitor/`、`config/` 和 `data/` 分层可以继续使用。不得仅为“看起来更整齐”移动源码。

### 3.2 按阶段增加的目标结构

以下结构按需形成，不要求一次性创建：

```text
EchoMind/
├── README.md
├── PLAYBOOK.md
├── CHANGELOG.md
├── docs/
│   ├── README.md
│   ├── business/
│   │   ├── BUSINESS_OVERVIEW.md
│   │   ├── USER_SCENARIOS.md
│   │   ├── BUSINESS_TERMS.md
│   │   ├── AGENT_CATALOG.md
│   │   ├── AGENT_BOUNDARY_MATRIX.md
│   │   ├── INTENT_CATALOG.md
│   │   ├── ENTITY_SCHEMA.md
│   │   ├── RESPONSE_STYLE_GUIDE.md
│   │   ├── ESCALATION_POLICY.md
│   │   └── agents/<agent_id>.md
│   ├── architecture/
│   │   ├── REQUEST_FLOW.md
│   │   ├── ROUTING_DESIGN.md
│   │   ├── RAG_DESIGN.md
│   │   ├── MEMORY_DESIGN.md
│   │   ├── TOOL_CONTRACTS.md
│   │   └── ADR/ADR-NNNN-<decision>.md
│   ├── operations/
│   │   ├── LOCAL_DEVELOPMENT.md
│   │   ├── DEPLOYMENT.md
│   │   ├── KNOWLEDGE_IMPORT.md
│   │   ├── EVALUATION_RUNBOOK.md
│   │   ├── MONITORING_RUNBOOK.md
│   │   ├── INCIDENT_RESPONSE.md
│   │   └── ROLLBACK.md
│   └── security/
│       ├── DATA_CLASSIFICATION.md
│       ├── PRIVACY_AND_RETENTION.md
│       ├── TOOL_PERMISSION_POLICY.md
│       └── SECRET_MANAGEMENT.md
├── data/
│   ├── demo_docs/
│   ├── knowledge/
│   │   ├── README.md
│   │   ├── sources/
│   │   ├── manifests/knowledge_manifest.json
│   │   └── processed/
│   ├── chroma/
│   └── eval/baseline.json
├── evaluation/
│   ├── evaluator.py
│   ├── cases/
│   ├── baselines/
│   └── reports/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── scripts/
├── tools/
└── .github/workflows/ci.yml
```

目录规则：

- 进入对应阶段时才创建目录和真实文件，不批量制造占位文件。
- `data/demo_docs/` 保留为演示数据；正式知识进入 `data/knowledge/sources/`。
- `data/chroma/` 是运行索引，不是知识的唯一事实来源。
- `data/chroma/`、`data/knowledge/processed/`、`evaluation/reports/` 和 `logs/` 应由 Git 忽略。
- 私钥、访问令牌、真实用户数据、生产日志永不提交 Git。
- `config/nginx/ssl/` 不得提交私钥。
- `tools/` 只有存在真实业务操作时才增加实现。
- 暂不建立独立 `prompts/` 加载体系。业务事实放在 `docs/business/`，运行时 System Prompt 按现有 Agent 机制维护。

---

## 4. 所有阶段通用的安全执行协议

### 4.1 开始前检查

```text
1. 明确任务属于阶段 0–7 中的哪一阶段。
2. 阅读 `PLAYBOOK.md`、相关源码和本阶段需要的 `CONFIRMED` 业务/架构文档。
3. 阅读该阶段所需的 CONFIRMED 业务文档。
4. 阅读所有拟修改文件的完整实现。
5. 搜索调用方、被调用方、API 模型和配置来源。
6. 检查 requirements.txt、Dockerfile、docker-compose.yml 和 .env.example。
7. 执行 git status，识别用户已有改动。
8. 记录当前可运行基线和已知失败。
```

不得覆盖、还原或格式化任务外的用户改动。相关文件已有未提交修改且无法安全兼容时，停止并说明冲突。

### 4.2 实施前必须明确

- 目标与非目标。
- 真实业务来源。
- 受影响调用链。
- 拟修改文件。
- API、存储和 Prompt 兼容性。
- 正常路径、失败路径与 fallback。
- 测试用例与验收阈值。
- 回滚方法。
- 尚未确认的内容。

优先进行最小、局部、可验证的修改。不得把业务改造扩大成依赖升级、目录重构或框架替换。

### 4.3 风险分级

| 等级 | 示例 | 最低验证要求 |
|---|---|---|
| 低 | 文档、非运行注释 | 内容、链接和 `git diff` 检查 |
| 中 | Prompt、Skill、Intent 样例 | 单元测试、针对性评测、回归样例 |
| 高 | 路由、协作、Tool、RAG 过滤、Memory | 单元 + 集成 + 失败路径 + API 冒烟 |
| 极高 | API 合同、存储结构、权限、生产配置、数据迁移 | 兼容方案、迁移与回滚演练、端到端评测、用户确认 |

### 4.4 实施约束

- 不新增依赖，除非现有依赖无法满足且用户明确批准。
- 不在无关任务中升级依赖、模型或镜像。
- 保持 FastAPI 请求链中的异步 I/O，不引入阻塞网络调用。
- 不吞异常；记录必要上下文并保留既有 fallback。
- 不在日志、异常、测试数据或文档中暴露密钥和真实敏感信息。
- 不直接编辑 `data/chroma/` 中的 SQLite/HNSW 文件。
- 不混淆 Skill、Knowledge、Memory 与 Tool。
- 不改变公开 API 字段、状态码和语义，除非任务明确要求且存在迁移方案。
- 不自行提交、推送、部署或删除数据，除非用户明确要求。

### 4.5 注释与日志约束

- 注释和 docstring 主要解释为什么需要某段逻辑、并发、fallback 或架构边界，不重复解释明显语法。
- 遵循周围代码的语言和风格，不为装饰重复添加中英文注释。
- 日志应帮助定位请求阶段、模块、Agent、Tool、耗时和是否使用 fallback。
- 不记录密钥、密码、访问令牌、完整敏感对话或逐 Token/逐循环调试内容。

### 4.6 验证顺序

```text
语法/静态检查
  ↓
目标模块测试
  ↓
单元测试
  ↓
集成测试
  ↓
端到端评测
  ↓
Docker/API 冒烟测试
  ↓
Git diff 与敏感信息检查
```

当前 `requirements.txt` 未包含 `pytest`，不得假设它可用。未获批准前可使用标准库 `unittest` 或项目现有评测入口；若引入测试框架，必须单独评估并更新依赖。

低风险检查示例：

```bash
git status --short
git diff --check
python -m compileall api agents core mcp memory monitor evaluation
docker compose config
```

启动服务和调用外部 LLM 可能消耗资源或产生费用。执行前确认环境和任务确实需要，禁止在无法确认的生产环境做破坏性测试。

### 4.7 完成报告

每次任务结束必须报告：

1. 修改的文件与行为变化。
2. 执行的验证及结果。
3. 未执行的验证及原因。
4. 兼容性、数据与安全风险。
5. 回滚方法。
6. 尚待业务确认的问题。

---

## 5. 阶段 0：业务建模与稳定基线

### 目标

先证明当前系统可运行，再把业务事实形成可审查文档。此阶段不改 Agent、路由或知识库行为。

### 用户输入

- 产品服务对象与业务目标。
- 用户类型、典型场景与真实问法。
- 候选 Agent 及各自业务负责人。
- 允许解决、禁止解决、必须澄清和必须转人工的问题。
- SOP、FAQ、政策、产品文档与术语。
- 敏感数据、合规与保存期限要求。
- 订单、物流、退款、工单等真实系统能力。
- 准确率、延迟、转人工率等质量目标。

材料不完整时可标记 `DRAFT` 或 `UNKNOWN`，但不得将未确认内容写进生产 Prompt 或路由。

### 按需创建

```text
README.md
docs/README.md
docs/business/BUSINESS_OVERVIEW.md
docs/business/USER_SCENARIOS.md
docs/business/BUSINESS_TERMS.md
docs/business/AGENT_CATALOG.md
docs/business/AGENT_BOUNDARY_MATRIX.md
docs/business/INTENT_CATALOG.md
docs/business/ENTITY_SCHEMA.md
docs/business/RESPONSE_STYLE_GUIDE.md
docs/business/ESCALATION_POLICY.md
docs/business/agents/<agent_id>.md
docs/operations/LOCAL_DEVELOPMENT.md
```

### 操作

1. 盘点真实目录、依赖、环境变量、容器和 API。
2. 验证 `.env` 未被 Git 跟踪，且不输出密钥值。
3. 验证 `GET /health`、`GET /docs` 和最小 `/chat` 链路。
4. 验证 Knowledge、Skills、Memory、Monitor 和 Evaluation 当前状态。
5. 保存改造前基线，不以历史 `baseline.json` 代替当前验证。
6. 将业务信息整理进 `docs/business/`。
7. 对所有 `UNKNOWN` 建立待确认清单。

### 阶段门禁

- 当前服务能否运行有明确结论。
- 当前失败被记录，没有被新改造掩盖。
- Agent 候选、主要边界和人工升级规则已确认。
- 不存在会改变 Agent 数量或核心职责的未决问题。

未满足门禁，不进入阶段 1。

---

## 6. 阶段 1：Agent 契约、画像与 System Prompt

### 目标

先把业务角色转成稳定 Agent 契约，再实现 Agent Type、class 与 System Prompt。本阶段不负责复杂路由、知识导入或真实外部操作。

### Agent 文档最低要求

`AGENT_CATALOG.md` 与 `docs/business/agents/<agent_id>.md` 应记录：

- 稳定 `agent_id`、显示名称和 Agent Type。
- 服务对象、目标、主职责和非职责。
- 允许回答与禁止承诺的内容。
- 所需实体字段。
- 可使用的 Skill、Tool 和知识范围。
- 转人工、转其他 Agent、拒绝与失败条件。
- 输出风格、格式和成功标准。

`AGENT_BOUNDARY_MATRIX.md` 必须覆盖重叠业务，明确主负责、协助、禁止和升级关系。

### 修改位置

| 动作 | 文件 |
|---|---|
| Agent Type、class、System Prompt 与实例池 | `agents/agent_orchestrator.py` |
| 启动组装，仅在必要时 | `api/main.py` |
| Agent 设计事实 | `docs/business/agents/<agent_id>.md` |
| Agent 测试 | `tests/unit/test_agents.py` |

### Prompt 规则

System Prompt 应包含身份、目标、负责范围、责任边界、必需信息、禁止行为、升级条件、不确定性处理和输出风格。

不要写入：

- 大量易变 FAQ 或产品事实；它们属于知识库。
- 详细且频繁变化的 SOP；它们优先属于 Skill。
- 密钥、凭证和真实用户信息。
- 尚未实现的 Tool 能力。

### 验证与门禁

- 每个 Agent 能正确处理职责内问题。
- 越界请求会拒绝、转交或升级。
- 不宣称能执行尚未接入的操作。
- 边界案例与边界矩阵一致。
- 原有 fallback 仍能工作。
- 所有 Prompt 规则能追溯至已确认业务文档。

---

## 7. 阶段 2：Intent、实体、路由与多 Agent 协作

### 目标

稳定判断“用户想做什么、需要哪些信息、由谁处理”，覆盖单 Agent、多 Agent、澄清、兜底与人工升级。

### 先完善

```text
docs/business/INTENT_CATALOG.md
docs/business/ENTITY_SCHEMA.md
docs/architecture/ROUTING_DESIGN.md
```

每个 Intent 必须包含稳定 ID、定义、正例、反例、易混淆例、主/协作 Agent、必需/可选实体、低置信度处理、组合规则、优先级和升级条件。

### 修改位置

| 动作 | 文件 |
|---|---|
| Intent、置信度和实体 | `core/intent_recognizer.py` |
| Intent-Agent 映射与协作 | `agents/agent_orchestrator.py` |
| API 合同，仅在必要时 | `api/main.py` |
| Intent/路由用例 | `evaluation/cases/intent_cases.json`、`routing_cases.json` |
| 单元测试 | `tests/unit/test_intent_recognizer.py`、`test_agent_routing.py` |
| 集成测试 | `tests/integration/test_chat_flow.py` |

### 必测场景

```text
单一明确 Intent
多 Intent
模糊或低置信度 Intent
未知 Intent
缺少关键实体
冲突 Intent
高风险或紧急请求
专业 Agent 不可用
并行 Agent 部分失败
General fallback
人工升级
```

多 Agent 协作必须定义主 Agent、并行/串行方式、响应合并、冲突处理、部分失败、重复 Tool/RAG 调用限制和延迟上限。

### 阶段门禁

- 每个 Intent 都有正反例和目标 Agent。
- 关键路由用例可重复执行。
- 低置信度不会被强制路由到高风险 Agent。
- 多 Agent 行为可解释、可测试、可降级。

---

## 8. 阶段 3：Skills 与业务 Tools

### 目标与概念边界

```text
System Prompt = Agent 的长期身份与边界
Skill         = 某类场景的处理流程和规范
Tool          = 查询或改变外部业务状态的真实能力
Knowledge     = 回答所依据的业务事实
```

### Skill 开发

主要位置：

```text
skills/<skill_name>/SKILL.md
core/skill_loader.py
skills/README.md
tests/unit/test_skill_loader.py
evaluation/cases/skill_cases.json
```

步骤：

1. 从已确认 SOP 提炼 Skill。
2. 定义稳定名称、适用 Agent、触发条件、处理步骤和禁止事项。
3. 验证发现、加载、过滤和 Prompt 注入。
4. 验证不会注入给无权使用的 Agent。
5. 测试遗漏、误命中、多个 Skill 同时命中和长度上限。
6. 保留现有 reload 能力。

RAG 触发不应随意复用 Skill 关键词：Skill 决定注入处理规范；RAG 触发策略决定是否检索事实。

### Tool 开发

只有拿到真实接口合同后才增加：

```text
docs/architecture/TOOL_CONTRACTS.md
docs/security/TOOL_PERMISSION_POLICY.md
tools/<tool_name>.py
mcp/tool_manager.py
api/main.py                     # 仅做必要注册与组装
tests/unit/tools/
tests/integration/test_tools.py
```

每个 Tool 必须定义授权 Agent、输入 JSON Schema、返回/错误结构、读写属性、幂等性、超时、重试、缓存、熔断、fallback、审计与脱敏。写操作还要定义用户确认和人工审核。

高风险权限不得只依赖 Prompt；执行层必须再次校验。

### 阶段门禁

- Skill 命中准确且保持 Agent 隔离。
- Tool 成功、超时、无权限、无数据和依赖故障均经测试。
- Agent 不会声称执行了实际未成功的操作。

---

## 9. 阶段 4：正式知识库与 RAG

### 目标

建立可追溯、可更新、可隔离、可重建的正式知识源，并保留查询改写、并行召回、去重和重排链路。

### 数据结构

```text
data/knowledge/
├── README.md
├── sources/<business_domain>/
├── manifests/knowledge_manifest.json
└── processed/                 # 生成内容，不提交
```

`data/demo_docs/` 继续只用于演示；`data/chroma/` 是可重建索引，不是唯一事实来源。

Manifest 最少记录：`document_id`、标题、版本、来源、负责人、生效日期、状态、Agent 范围、Intent 范围、敏感等级和源文件路径/校验值。

### 修改位置

| 动作 | 文件 |
|---|---|
| 知识源与版本清单 | `data/knowledge/` |
| 导入、切分、collection、查询 | `mcp/knowledge_base.py` |
| 改写、召回、去重、重排 | `mcp/tool_manager.py` |
| `/chat` 检索触发与上下文组装 | `api/main.py` |
| 设计与导入手册 | `docs/architecture/RAG_DESIGN.md`、`docs/operations/KNOWLEDGE_IMPORT.md` |
| 脚本 | `scripts/import_knowledge.py`、`verify_knowledge.py`、`rebuild_knowledge_index.py` |
| 测试 | `tests/unit/test_knowledge_base.py`、`tests/integration/test_rag_flow.py`、`evaluation/cases/rag_cases.json` |

### 安全与质量

- 导入前核对版权、隐私、敏感等级、有效期和负责人。
- 明确知识是全 Agent 共享还是按 metadata 过滤，禁止猜测。
- 检索结果携带可追溯 metadata。
- 能重建索引并撤销失效内容。
- 测试无结果、错误结果、过期内容、重复内容、跨 Agent 泄漏和提示注入。
- 不直接修改 ChromaDB 数据文件。
- 生产数据重建、删除、覆盖必须单独获得确认并有恢复方案。

### 阶段门禁

- 重要回答能追溯到版本化知识源。
- Agent 访问范围符合业务边界。
- RAG 质量不低于已确认基线。
- 删除、失效和重建流程已经验证。

---

## 10. 阶段 5：Memory、用户画像与数据治理

### 目标

定义系统“记住什么、保存在哪里、保存多久、谁能使用”，而不是无条件保存更多信息。

### 先创建

```text
docs/architecture/MEMORY_DESIGN.md
docs/business/ENTITY_SCHEMA.md
docs/security/DATA_CLASSIFICATION.md
docs/security/PRIVACY_AND_RETENTION.md
```

### 修改位置

```text
memory/conversation_memory.py
api/main.py
evaluation/cases/memory_cases.json
tests/unit/test_memory.py
tests/integration/test_memory_flow.py
```

### 字段设计要求

逐字段定义名称、类型、来源、用途、存储层、敏感等级、写入条件、更新规则、TTL、删除方式、用户同意、可读 Agent、冲突与纠错方法。

必须测试新会话、连续会话、同一用户不同会话、用户隔离、Redis/ChromaDB 故障、压缩失真、画像冲突与删除、敏感数据泄漏。

### 阶段门禁

- 每个持久化字段都有业务依据、保存期限和删除策略。
- 用户间、collection 间无串用。
- 存储依赖故障存在明确 fallback，不产生错误承诺。

---

## 11. 阶段 6：评测、监控、安全与回归门禁

### 目标

把主观判断转换为可重复指标，及时发现 Prompt、路由、Agent、Tool、RAG 与 Memory 的退化。

### 评测资产

```text
evaluation/cases/
├── intent_cases.json
├── routing_cases.json
├── agent_boundary_cases.json
├── skill_cases.json
├── tool_cases.json
├── rag_cases.json
├── memory_cases.json
├── safety_cases.json
└── response_cases.json
evaluation/baselines/
evaluation/reports/             # 不提交运行报告
docs/operations/EVALUATION_RUNBOOK.md
```

用例覆盖正常、边界、歧义、对抗、依赖失败与安全场景，并移除真实个人信息。不得为了提升指标删除失败用例。

### 指标

- Intent：Accuracy、Macro-F1、低置信度表现。
- 路由：目标 Agent、多 Agent、fallback、升级准确性。
- Agent：职责内正确率、越界率、错误承诺率。
- Skill：应命中、误命中、隔离与长度。
- RAG：召回、相关性、过期知识、跨域泄漏与无答案处理。
- Tool：成功率、超时、权限、幂等与错误陈述。
- Memory：一致性、隔离、压缩损失与隐私。
- 最终回答：相关性、准确性、完整性、帮助性与安全性。

LLM-as-Judge 只能作为部分证据；关键规则使用确定性断言。基线记录业务版本、知识版本、模型配置和评测集版本。

端到端评测必须经过真实的 `AgentOrchestrator.run()` 编排链路，覆盖实际 Intent、路由、Agent 和 Skill 行为。Mock 只可用于隔离外部 LLM、Redis、ChromaDB 或业务系统的单元测试，不能用 Mock 结果证明完整 `/chat` 业务链路已经通过。

### 监控位置与范围

```text
monitor/performance_monitor.py
config/prometheus.yml
config/alerts/alert_rules.yml
config/grafana/dashboards/
config/grafana/provisioning/
docs/operations/MONITORING_RUNBOOK.md
docs/operations/INCIDENT_RESPONSE.md
```

监控请求量、错误率、P50/P95/P99 延迟、Intent 分布、低置信度率、fallback 率、Agent/Tool/RAG 状态、依赖健康、人工升级和安全拒绝。监控不得记录完整敏感对话；告警阈值必须有业务依据。

### CI

测试稳定后再增加 `.github/workflows/ci.yml`，至少运行语法检查、单元测试、不依赖真实密钥的集成测试、`docker compose config`、敏感信息和意外大文件检查。真实 LLM 测试单独分组。

### 阶段门禁

- 关键指标和阈值已确认。
- 每类变更都有对应回归集。
- 告警有负责人、处理动作和恢复判断。
- 高风险安全用例通过，否则阻止发布。

---

## 12. 阶段 7：全链路验收、发布与持续迭代

### 目标

验证业务改造整体可运行、可观察、可回滚，然后发布。优化和重构只依据测量结果进行。

### 发布前清单

```text
[ ] 业务文档为 CONFIRMED，没有阻塞发布的 UNKNOWN。
[ ] 代码、Prompt、Skills、Tool 与知识版本一致。
[ ] API 兼容，或已有确认的迁移方案。
[ ] 单元、集成、端到端和安全测试达到门禁。
[ ] 当前基线已保存并带版本信息。
[ ] Docker Compose 配置有效。
[ ] /health、/chat、/search、/skills 和关键 Tool 已冒烟验证。
[ ] Redis、ChromaDB、Prometheus、Nginx 状态正常。
[ ] 日志无密钥或敏感数据。
[ ] 知识索引与 manifest 对应。
[ ] 监控、告警和事故负责人明确。
[ ] 数据迁移、备份和回滚经过演练。
[ ] 变更记录和部署手册已更新。
```

建议形成：

```text
CHANGELOG.md
docs/operations/DEPLOYMENT.md
docs/operations/ROLLBACK.md
docs/operations/INCIDENT_RESPONSE.md
scripts/smoke_test.py
```

### 发布规则

- 保存可识别的代码、配置、知识与评测版本。
- 优先灰度或小流量验证。
- 不在发布时顺带升级依赖、模型或数据库格式。
- 核心路由、权限、数据隔离或安全回归时立即停止。
- 回滚同时考虑代码、配置、Skills、知识索引与数据结构。

发布后比较 Intent/Agent 分布、低置信度、fallback、人工升级、Tool/RAG 错误、延迟、解决率、重复提问、安全拒绝和费用变化。只有测量确认瓶颈后才重构，之后重新跑完整回归。

### 阶段门禁

- 目标环境达到确认指标。
- 关键问题有告警和处理手册。
- 可恢复到上一稳定版本。
- 决策、已知限制和后续事项已记录。

---

## 13. 阶段依赖关系

```text
阶段 0：业务事实 + 可运行基线
  ↓
阶段 1：Agent 契约 + System Prompt
  ↓
阶段 2：Intent + 实体 + 路由 + 协作
  ↓
阶段 3：Skills + Tools
  ↓
阶段 4：知识源 + RAG
  ↓
阶段 5：Memory + 用户画像 + 数据治理
  ↓
阶段 6：评测 + 监控 + 安全门禁
  ↓
阶段 7：全链路验收 + 发布 + 持续迭代
```

这是主顺序，不代表评测和安全只能最后开始：评测用例应从阶段 0 持续积累，安全要求贯穿所有阶段。后置运行能力仍须建立在前置业务契约已确认的基础上。

---

## 14. 业务材料存放与使用

| 信息 | 存放位置 | 后续用途 |
|---|---|---|
| 产品、用户、业务目标 | `docs/business/BUSINESS_OVERVIEW.md` | 判断功能方向 |
| 用户场景与真实问法 | `docs/business/USER_SCENARIOS.md` | Intent、路由、评测 |
| 业务术语 | `docs/business/BUSINESS_TERMS.md` | 实体、检索与命名 |
| Agent 清单 | `docs/business/AGENT_CATALOG.md` | Agent Type、class、Prompt |
| Agent 边界 | `docs/business/AGENT_BOUNDARY_MATRIX.md` | 路由、拒绝、协作、升级 |
| Agent 详细要求 | `docs/business/agents/<agent_id>.md` | Prompt、Skill 与测试 |
| Intent 定义与例句 | `docs/business/INTENT_CATALOG.md` | 识别器和路由用例 |
| 实体字段 | `docs/business/ENTITY_SCHEMA.md` | 提取、校验、Tool、Memory |
| 回答风格 | `docs/business/RESPONSE_STYLE_GUIDE.md` | Prompt 与回答评测 |
| 转人工规则 | `docs/business/ESCALATION_POLICY.md` | 路由、安全、失败处理 |
| FAQ、政策、产品手册 | `data/knowledge/sources/<domain>/` | RAG 导入与版本管理 |
| 知识来源和权限 | `data/knowledge/manifests/knowledge_manifest.json` | 过滤、审计、重建 |
| 外部系统接口 | `docs/architecture/TOOL_CONTRACTS.md` | Tool 设计与测试 |
| 隐私与保存规则 | `docs/security/` | Memory、日志、Tool、数据治理 |
| 验收问题和期望行为 | `evaluation/cases/` | 自动评测与回归门禁 |

文档开头建议包含：

```text
Status: DRAFT | CONFIRMED | DEPRECATED
Owner: <负责人或 UNKNOWN>
Last Updated: YYYY-MM-DD
Version: <版本>
```

只有 `CONFIRMED` 内容可作为高风险业务逻辑的直接实现依据。

---

## 15. 必须停止并请求确认的情况

- Agent 数量、职责或边界存在冲突。
- 高风险操作缺少授权、确认或人工审核规则。
- 需要新增依赖、升级模型、改变数据库结构或破坏 API 兼容。
- 需要删除、覆盖或迁移真实数据。
- 无法判断当前环境是本地、测试还是生产。
- 相关文件包含无法安全合并的未提交修改。
- 知识来源、有效期、权限或敏感等级不明。
- 评测失败涉及资金、隐私、权限、安全或跨用户泄漏。
- 需要真实外部接口但缺少测试环境或接口合同。
- 回滚路径不可用。

普通的内部实现细节可在说明可逆假设后采用最小方案；不得用“合理假设”替代关键业务授权。

---

## 16. 单次开发任务模板

```markdown
# 任务名称

## 所属阶段
阶段 N

## 目标

## 非目标

## 已确认业务依据
- 文件：
- 章节：
- 状态：CONFIRMED

## UNKNOWN / 待确认

## 受影响调用链

## 拟修改文件

## API / 数据 / 安全影响

## 实施步骤

## 测试用例
- 正常：
- 边界：
- 失败：
- 安全：
- 回归：

## 验收标准

## 回滚方法

## 最终结果
- 修改：
- 验证：
- 未验证：
- 风险：
```

---

## 17. Definition of Done

```text
[ ] 结论来自当前源码或 CONFIRMED 业务文档。
[ ] 修改范围与任务一致，没有额外重构。
[ ] 没有未经批准的依赖或版本升级。
[ ] API、异步行为、fallback 和模块边界得到保留。
[ ] 正常、边界、失败、安全和回归路径已考虑。
[ ] 测试和评测结果可复现。
[ ] 没有提交密钥、日志、索引或真实用户数据。
[ ] 文档、代码、Skills、知识和评测集保持一致。
[ ] git diff 已检查，没有覆盖无关改动。
[ ] 未验证项和 UNKNOWN 已明确报告。
[ ] 回滚步骤明确且与变更范围匹配。
```

最终原则：

```text
先确认业务事实
→ 再定义 Agent 契约
→ 再实现路由与能力
→ 同步建立测试和安全边界
→ 最后用全链路评测决定是否发布
```

信息不足时，宁可保留 `UNKNOWN` 并请求确认，也不要把猜测固化进 Prompt、路由、知识库、Memory 或 Tool。
