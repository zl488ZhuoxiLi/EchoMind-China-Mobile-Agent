# EchoMind Agent 与知识库架构分析

> 分析日期：2026-07-24  
> 分析对象：`/Users/lizhuoxi/项目/EchoMind` 当前源码与只读部署状态  
> 约束：仅分析；未修改任何源码、配置或运行数据。

## 核心结论

1. 不同 Agent 的能力差异主要来自三个地方：
   - Python 子类中写死的 `agent_type` 和 `system_prompt`；
   - 按 `agents + keywords` 匹配后动态注入的 Skill；
   - Orchestrator 的意图路由和复合问题关键词路由。
2. 所有 Agent 使用同一个 LLM 配置、同一个 `SkillManager`，并接收同一套 Memory/RAG context。
3. 当前没有 Agent 专属 Tool，也没有 Agent 专属知识库。RAG 在 Agent 调度之前统一执行，然后把同一份检索结果交给被选中的一个或多个 Agent。
4. `IntentRecognizer` 只输出一个主 Intent；复合问题不是用“多 Intent 数组”表示，而是由 Orchestrator 再扫描原消息中的领域关键词，生成多个 Agent target。
5. 当前部署中的应用没有连上独立 ChromaDB 服务，而是降级到 `/app/data/chroma` 本地嵌入式库；在线 API 报告其中有 6 个知识片段。独立 ChromaDB 容器当前返回空 collection 列表。

---

## 1. Agent 总览

### 1.1 当前有哪些 Agent

|Agent|文件位置|职责|
|-|-|-|
|`GeneralAgent`|`agents/agent_orchestrator.py:171`|通用客服、基础咨询、默认兜底|
|`TechnicalAgent`|`agents/agent_orchestrator.py:179`|故障排查、错误诊断、系统配置|
|`BillingAgent`|`agents/agent_orchestrator.py:187`|账单、退款、发票、订阅|
|`ESCALATION`|`agents/agent_orchestrator.py:35`|仅为 `AgentType` 枚举占位，不存在可执行的 `EscalationAgent` class|

三个可执行 Agent 都定义在同一个文件中，并继承：

```text
BaseAgent
├── GeneralAgent
├── TechnicalAgent
└── BillingAgent
```

`BaseAgent` 位于 `agents/agent_orchestrator.py:99`，统一封装：

- LLM Client 和模型；
- `handle()` 执行与异常处理；
- Agent 调用统计；
- system prompt 构建；
- Skill 注入；
- LLM 调用；
- 转人工关键词检查。

### 1.2 Agent 是 class 还是配置驱动

结论：

```text
Agent 本体是 Python class 驱动，不是配置文件驱动。
```

依据：

- Agent 类型、职责 Prompt、路由表、Agent 池都直接写在 `agents/agent_orchestrator.py`。
- `config/` 当前只有：
  - `config/nginx/nginx.conf`
  - `config/prometheus.yml`
- 没有发现 Agent YAML、JSON 或 TOML 配置。

环境变量只配置所有 Agent 共用的基础设施：

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_MODEL`
- `ECHOMIND_SKILLS_DIR`
- `ECHOMIND_SKILLS_MAX_PROMPT_CHARS`

Skills 是文件驱动的行为规则，但 Skills 不负责创建 Agent class，也不修改路由表。

### 1.3 Agent 在哪里初始化

第一层初始化在 `api/main.py:69` 的 `lifespan()`：

```python
_orchestrator = AgentOrchestrator(
    api_key=cfg["api_key"],
    base_url=cfg.get("base_url"),
    model=cfg["model"],
    skill_manager=_skill_manager,
)
```

第二层初始化在 `agents/agent_orchestrator.py:216` 的 `AgentOrchestrator.__init__()`：

```python
self._pool = {
    AgentType.GENERAL:   [GeneralAgent(client, model, skill_manager)],
    AgentType.TECHNICAL: [TechnicalAgent(client, model, skill_manager)],
    AgentType.BILLING:   [BillingAgent(client, model, skill_manager)],
}
```

初始化关系：

```text
FastAPI lifespan
  ↓
读取公共 LLM 配置
  ↓
加载 SkillManager
  ↓
创建 AgentOrchestrator
  ↓
创建一个共享 AsyncAnthropic client
  ↓
创建 General / Technical / Billing 各一个实例
```

当前每个类型只有一个 Agent 实例。`_pool` 的数据结构支持同类放多个实例，但源码没有创建更多实例。

---

## 2. Agent 能力来源分析

### 2.1 System Prompt

Agent 的固定 system prompt 是子类的 class attribute，位于 `agents/agent_orchestrator.py:171-192`。

#### GeneralAgent

```text
你是 EchoMind 智能客服。友好、简洁地回答用户问题。
如果问题超出你的能力范围，明确说明并建议转接专业客服。
```

作用：

- 建立通用客服身份；
- 要求回答友好、简洁；
- 超出能力范围时建议转专业客服。

#### TechnicalAgent

```text
你是技术支持专家。专注于：故障排查、错误诊断、系统配置。
提供清晰的步骤化解决方案。遇到需要后台操作的问题，说明需要升级处理。
```

作用：

- 把 LLM 限定为技术支持角色；
- 偏向诊断和步骤化排障；
- 后台操作问题需要升级。

#### BillingAgent

```text
你是账单服务专家。专注于：账单查询、退款申请、发票问题、订阅管理。
对财务问题保持准确和专业。涉及实际退款操作时，说明需要人工审核。
```

作用：

- 把 LLM 限定为财务/账单角色；
- 要求准确、专业；
- 避免在没有后台能力时直接承诺退款。

### 2.2 System message 如何进入 LLM

调用位置：`agents/agent_orchestrator.py:138-154`。

```python
resp = await self._client.messages.create(
    model=self._model,
    max_tokens=1024,
    system=self._build_system_prompt(req),
    messages=messages,
)
```

最终 system prompt 由 `_build_system_prompt()` 生成：

```text
子类固定 system_prompt
  +
[动态 Skills]
  +
当前消息和当前 Agent 匹配到的 Skill 文本
```

Memory 与 RAG 不放在 system 参数中，而是被包装成一条 `[背景信息]` user message，再补一条“已了解背景”的 assistant message，最后追加真实用户消息。

### 2.3 Skill

#### Skill 文件

|Agent|Skill 文件|Skill 作用|
|-|-|-|
|GeneralAgent|`skills/general_customer_service/SKILL.md`|接待、信息澄清、问题分流、投诉和转人工边界|
|TechnicalAgent|`skills/technical_support/SKILL.md`|故障排查、错误码、API/SDK、部署配置、安全边界和升级条件|
|BillingAgent|`skills/billing_support/SKILL.md`|扣款、退款、发票、订阅、核验字段、财务审核和禁止承诺|

#### Skill 如何加载

主要文件：`core/skill_loader.py`。

启动调用：`api/main.py:94-100`。

```text
ECHOMIND_SKILLS_DIR
  ↓
SkillManager.load()
  ↓
_discover_files()
  ↓
优先发现 **/SKILL.md
  ↓
解析 Markdown front matter 和正文
  ↓
转换为 Skill dataclass
```

支持文件：

- `SKILL.md`
- 普通 `.md`
- `.txt`
- `.json`

Markdown front matter 由项目自写解析器处理，没有使用 YAML 依赖。

#### Skill 如何匹配 Agent

入口：`core/skill_loader.py:27` 的 `Skill.matches()`。

匹配条件：

1. `enabled` 必须为真；
2. 如果 Skill 声明了 `agents`，当前 `agent_type` 必须在其中；
3. 如果 Skill 声明了 `keywords`，用户消息至少命中一个关键词；
4. 没有 `keywords` 的 Skill 会作为全局 Skill。

当前三个 Skill 的 Agent 范围：

```text
通用客服接待规范  → agents: general
技术支持处理规范  → agents: technical
账单退款处理规范  → agents: billing
```

例如输入：

```text
登录失败，并且重复扣款
```

- TechnicalAgent：
  - Agent 匹配 `technical`；
  - 消息命中 `登录失败`；
  - 注入 `技术支持处理规范`。
- BillingAgent：
  - Agent 匹配 `billing`；
  - 消息命中 `重复扣款`、`扣款`；
  - 注入 `账单退款处理规范`。
- GeneralAgent：
  - 当前并行目标中没有 GeneralAgent；
  - 即使执行 GeneralAgent，该消息也没有命中其主要关键词时，不保证注入通用 Skill。

#### Skill 如何注入 Prompt

```text
BaseAgent._build_system_prompt()
  ↓
SkillManager.prompt_for(req.message, self.agent_type.value)
  ↓
筛选匹配 Skill
  ↓
Skill.to_prompt_block()
  ↓
按 ECHOMIND_SKILLS_MAX_PROMPT_CHARS 截断
  ↓
追加到固定 system_prompt
```

关键代码：

- `agents/agent_orchestrator.py:156-163`
- `core/skill_loader.py:122-172`

### 2.4 配置

Agent 共享的配置关系：

|配置|来源|作用范围|
|-|-|-|
|API Key|`ANTHROPIC_API_KEY`|所有 Agent、Intent、RAG 重排、Memory、Evaluation|
|Base URL|`ANTHROPIC_BASE_URL`|所有 LLM 调用|
|Model|`ANTHROPIC_MODEL`|所有 Agent 使用同一个模型|
|Skill 目录|`ECHOMIND_SKILLS_DIR`|同一个 SkillManager|
|Prompt 预算|`ECHOMIND_SKILLS_MAX_PROMPT_CHARS`|每次动态 Skill 总长度|

没有发现以下按 Agent 区分的配置：

- 不同模型；
- 不同 temperature；
- 不同 max token 配置文件；
- 不同知识库 ID；
- 不同 Tool 白名单；
- 不同 Chroma collection。

### 2.5 Tool

#### 当前有哪些 Tool

`tools/` 目录当前没有有效文件。

真正的 Tool 抽象位于：

- `mcp/tool_manager.py`
- `mcp/knowledge_base.py`

启动时只注册了一个 Tool：

```text
knowledge_search
```

注册代码：`api/main.py:144-159`。

它的 handler 是：

```python
kb.search_handler
```

#### Agent 是否拥有不同 Tool

结论：

```text
否。
```

依据：

- `BaseAgent`、三个子类和 `AgentOrchestrator` 都没有 ToolManager 字段。
- Agent 源码中没有 `knowledge_search`、`MCPToolManager` 或 Tool 调用。
- 唯一的 `_tool_manager` 全局对象在 `api/main.py`。

#### Tool 是否共享

结论：

```text
ToolManager 是应用级共享对象，但当前并不是由 Agent 自主调用。
```

真实关系：

```text
api/main.py:/chat
  ↓
应用级 MCPToolManager
  ↓
knowledge_search
  ↓
检索结果变成 context
  ↓
AgentOrchestrator
  ↓
一个或多个 Agent
```

因此，不能把当前结构描述为“TechnicalAgent 拥有 knowledge_search Tool”。
更准确的说法是：

> `/chat` 主链在选择 Agent 之前统一调用共享的知识检索工具，再把结果作为背景信息传给 Agent。

### 2.6 Skill、Prompt、配置、Tool、知识库的关系

```text
环境配置
├─ 决定公共 LLM client/model
├─ 决定 Skill 目录
└─ 决定 ChromaDB 地址

Agent class
├─ 决定 agent_type
└─ 提供固定 system_prompt

SkillManager
├─ 按 agent_type 过滤
├─ 按用户消息关键词过滤
└─ 把业务规则追加到 system_prompt

MCPToolManager
└─ 在 /chat 中统一检索 knowledge_base

Memory + RAG
└─ 合并为 Request.context，作为背景消息传给 Agent

Agent
└─ 固定 Prompt + 动态 Skill + 共享背景 context → LLM
```

不同 Agent 的“能力”目前主要是 Prompt 层的行为差异，不代表它们拥有不同的真实后台系统权限。例如 BillingAgent 没有订单/支付系统 Tool，TechnicalAgent 也没有日志或服务器管理 Tool。

---

## 3. Intent 与 Agent 路由分析

### 3.1 IntentRecognizer 输出格式

数据结构位于 `core/intent_recognizer.py:46-53`：

```python
@dataclass
class IntentResult:
    intent: IntentCategory
    confidence: float
    urgency: UrgencyLevel
    entities: Dict[str, List[str]]
    reasoning: str
    latency_ms: float
```

字段含义：

|字段|含义|
|-|-|
|`intent`|一个主意图枚举|
|`confidence`|当前实现取 LLM 识别结果的 confidence|
|`urgency`|LOW、MEDIUM、HIGH、CRITICAL|
|`entities`|订单号、产品、日期、金额、错误码等|
|`reasoning`|LLM 给出的简短判断理由|
|`latency_ms`|识别耗时|

Intent 候选：

```text
query, complaint, request, greeting, escalation,
technical, billing, account, feedback, other
```

### 3.2 多 Intent 如何表示

结论：

```text
当前没有多 Intent 数据结构。
```

`IntentResult.intent` 是单个 `IntentCategory`，不是列表。

识别器会用 LLM、Embedding/本地 n-gram、Pattern 三路结果加权投票，最终只选一个最高分意图。相关代码：

- `core/intent_recognizer.py:118-165`
- `core/intent_recognizer.py:272-292`

### 3.3 “登录失败，并且重复扣款”为什么调用两个 Agent

第一步，`IntentRecognizer` 仍然只会输出一个主意图。具体是 `technical` 还是 `billing` 取决于运行时 LLM 与加权投票结果：

```text
UNKNOWN
需要进一步确认
```

第二步，Orchestrator 不只依赖这个主意图。它调用：

```python
collaboration = self._collaboration_targets(req)
```

代码位置：`agents/agent_orchestrator.py:334-354`。

它扫描原始消息：

```python
technical_kws = [
    "崩溃", "报错", "error", "crash",
    "无法登录", "登录失败", "500", "401"
]

billing_kws = [
    "退款", "扣款", "发票", "账单",
    "支付", "订阅", "refund", "invoice"
]
```

输入同时命中：

```text
登录失败 → TechnicalAgent
重复扣款 → BillingAgent
```

所以得到：

```python
[AgentType.TECHNICAL, AgentType.BILLING]
```

### 3.4 Orchestrator 如何选择 Agent

主入口：`agents/agent_orchestrator.py:247`。

#### 复合问题

如果 `_collaboration_targets()` 返回两个以上 Agent：

```python
return await self.run_parallel(req, collaboration)
```

#### 单领域问题

调用 `_route(intent, urgency)`：

|条件|目标|
|-|-|
|CRITICAL|`ESCALATION`，但池中没有实例，执行时降级 General|
|technical|TechnicalAgent|
|billing|BillingAgent|
|account|BillingAgent|
|escalation|目标为 ESCALATION，但不存在实例，实际降级 General|
|其他|GeneralAgent|

#### 同类实例选择

`_best_agent()` 使用：

```python
max(agents, key=lambda a: a.stats.routing_score())
```

`routing_score` 综合：

- 成功率；
- 平均延迟；
- Monitor penalty。

但当前每种 Agent 只有一个实例，因此性能路由暂无同类替代对象。

#### 执行失败降级

专属 Agent 返回 `success=False` 时，`_execute()` 会再次调用 GeneralAgent。

### 3.5 是否支持并行执行

结论：

```text
支持。
```

实现：`agents/agent_orchestrator.py:287-312`。

```python
tasks = [self._execute(req, at) for at in agent_types]
responses = await asyncio.gather(*tasks, return_exceptions=True)
```

合并方式不是再次调用总结 Agent，而是简单拼接：

```text
[technical]
TechnicalAgent 的回答

[billing]
BillingAgent 的回答
```

并行结果的 `agent_type` 字段取 `agent_types[0]`，因此它不能完整表达“两个 Agent 都参与了”。

### 3.6 路由流程

```text
User Input
  ↓
IntentRecognizer.recognize()
  ↓
一个主 IntentResult
  ↓
AgentOrchestrator._collaboration_targets()
  ├─ 主 Intent
  └─ 原始消息领域关键词
  ↓
一个 target → _route() / _best_agent()
多个 target → run_parallel()
  ↓
BaseAgent.handle()
  ↓
LLM 执行
```

---

## 4. 知识库分析

### 4.1 Chroma Collections

源码定义和当前本地嵌入式库中存在三个 collection：

|名称|用途|定义文件|
|-|-|-|
|`knowledge_base`|RAG 业务知识文档|`mcp/knowledge_base.py:32`|
|`episodic`|压缩后的跨会话情景记忆|`memory/conversation_memory.py:120`|
|`user_profile`|用户偏好和实体画像|`memory/conversation_memory.py:122`|

只有 `knowledge_base` 是业务知识库。`episodic` 和 `user_profile` 属于 Memory，不是公共业务文档。

### 4.2 初始化逻辑

`KnowledgeBase` 初始化位于 `mcp/knowledge_base.py:34-68`：

```text
尝试 chromadb.HttpClient
  ↓ 失败
降级 chromadb.PersistentClient(chroma_path)
  ↓
get_or_create_collection("knowledge_base")
  ↓
如果 count == 0
  ↓
_load_default_docs()
```

添加文档时：

```text
文档
  ↓
按约 500 字切片
  ↓
生成稳定 MD5 ID
  ↓
ChromaDB 默认 embedding
  ↓
collection.add()
```

### 4.3 当前部署实际使用哪一个 ChromaDB

只读部署检查结果：

- `echomind-app`：healthy。
- `echomind-chromadb`：healthy。
- 应用 `/knowledge/stats`：`total_chunks = 6`。
- 应用启动日志：

```text
ChromaDB 服务不可用，使用本地嵌入式模式: /app/data/chroma
知识库 ChromaDB 服务不可用，使用本地模式: /app/data/chroma
知识库已加载: 6 个文档片段
```

- 独立 `echomind-chromadb` 的 `/api/v1/collections` 当前返回：

```json
[]
```

结论：

> 当前运行中的 EchoMind 实际使用绑定到 `/app/data/chroma` 的本地嵌入式 ChromaDB，而不是独立 ChromaDB 容器。

独立 ChromaDB 容器健康但应用连接失败的具体原因：

```text
UNKNOWN
需要进一步确认
```

### 4.4 Agent 是否共享知识库

```text
是否共享：是。
```

依据：

1. `api/main.py:272` 在调用 `AgentOrchestrator.run()` 之前执行 `_build_knowledge_context()`。
2. `_build_knowledge_context()` 固定调用唯一的：

```python
search_with_rewrite("knowledge_search", message, top_k=3)
```

3. 检索结果被合并进一个 `full_context`。
4. 同一个 `OrcReq` 被传入一个或多个 Agent。
5. `KnowledgeBase.search()` 的 Chroma query 没有 Agent、领域、租户或文档类型过滤条件。

关键调用：

```python
results = self._collection.query(
    query_texts=[query],
    n_results=top_k,
)
```

因此：

```text
TechnicalAgent 检索范围：整个 knowledge_base collection
BillingAgent 检索范围：整个 knowledge_base collection
GeneralAgent 检索范围：整个 knowledge_base collection
```

区别只来自查询文本的语义相关性和 LLM rerank，不来自 collection 隔离或 metadata filter。

复合问题中，RAG 也只执行一次；TechnicalAgent 和 BillingAgent 接收同一份 Top-K 知识上下文。

### 4.5 当前在线知识库内容

当前应用报告 6 个片段；仓库绑定的 ChromaDB 文件中也确认是以下 6 个文档，每篇 1 个 chunk：

|名称|内容摘要|
|-|-|
|退款政策|7 天无理由退款、1-3 个工作日审核、5-7 个工作日原路退回、发货后的退货规则|
|订单查询|订单状态、物流更新时间、超时未收到和异常订单处理|
|账户安全|密码要求、密码重置、异常登录锁定、两步验证、安全提醒|
|技术故障排查|应用崩溃、401 登录失败、页面加载慢、支付失败、500 错误|
|会员与积分|积分累计和抵扣、会员等级折扣、积分有效期、生日双倍积分|
|配送说明|标准/加急/同城配送时效和费用、偏远地区、地址修改|

这些内容来自 `mcp/knowledge_base.py:173-247` 的 `_load_default_docs()`，并与当前 Chroma `knowledge_base` 记录一致。

### 4.6 仓库中的演示文档

`data/demo_docs/` 还有两份文件，但当前启动流程不会自动读取它们。

#### `data/demo_docs/sample_knowledge.json`

包含 6 篇候选导入文档：

|名称|内容|
|-|-|
|EchoMind 产品介绍|多 Agent、记忆、监控和评测能力介绍|
|订阅计划与定价|基础版、专业版、企业版定价和权益|
|API 接入指南|API Key、`POST /chat`、响应字段和 `/docs`|
|常见集成问题|API 超时、多轮对话、语言、知识库导入|
|数据安全与隐私|TLS、数据隔离、保留策略、私有部署、合规声明|
|版本更新日志 v2.0|意图识别、RAG、记忆、Monitor、Evaluation 更新说明|

#### `data/demo_docs/troubleshooting.md`

包含：

- 应用崩溃；
- 401 认证失败；
- 403 权限不足；
- 支付失败；
- 重复扣款；
- 页面加载慢；
- 连接超时。

是否已通过 API 另外导入这两份文件：

```text
否。
```

依据：当前在线/本地 `knowledge_base` 只有 6 个默认文档标题，没有上述演示文档标题。

### 4.7 Skill 不是知识库

`skills/*/SKILL.md` 和 `knowledge_base` 是两条不同链路：

|Skill|Knowledge Base|
|-|-|
|业务行为规则、SOP、禁止事项|可检索的事实/业务知识|
|按 Agent + keyword 匹配|按向量相似度检索|
|进入 system prompt|进入背景 context|
|每个 Agent 可不同|当前所有 Agent 共享|

---

## 5. 完整请求链路：`登录时报401错误`

注意：源码的真实顺序是先做 Knowledge Retrieval，再选择 Agent。不是 Agent 自己决定是否调用知识库。

### 第 1 步：接收请求

文件：`api/main.py`  
函数：`chat()`，`api/main.py:249`

作用：

- 接收 `message/user_id/conv_id`；
- 未传 `conv_id` 时生成 UUID；
- 开始 Memory、RAG 和 Agent 主链。

### 第 2 步：读取 Memory

文件：`memory/conversation_memory.py`  
函数：`MemoryManager.get_context()`，约 `:206`

作用：

- Redis 最近消息；
- Chroma `episodic` 相关历史；
- Chroma `user_profile`；
- Redis 会话摘要。

结果由 `MemoryContext.to_prompt_text()` 格式化。

### 第 3 步：Knowledge Retrieval

文件：`api/main.py`  
函数：`_build_knowledge_context()`，`:307`

`登录时报401错误` 不是纯寒暄，因此进入检索：

```text
_build_knowledge_context()
  ↓
MCPToolManager.search_with_rewrite()
  ↓
rewrite_query()：LLM 生成多个子查询
  ↓
并行 knowledge_search
  ↓
KnowledgeBase.search_handler()
  ↓
KnowledgeBase.search()
  ↓
Chroma knowledge_base.query()
  ↓
合并去重
  ↓
LLM rerank
  ↓
Top 3
```

相关文件：

- `mcp/tool_manager.py:251`：查询改写；
- `mcp/tool_manager.py:281`：并行召回和合并；
- `mcp/tool_manager.py:324`：LLM 重排；
- `mcp/knowledge_base.py:99`：Chroma 查询。

现有知识中有“技术故障排查”，正文明确包含 401 登录失败。

实际 Top-K 的精确顺序受 embedding 和 LLM rerank 运行结果影响：

```text
UNKNOWN
需要进一步确认
```

### 第 4 步：合并背景

文件：`api/main.py`  
代码：`:272-284`

```text
MemoryContext.to_prompt_text()
  +
[知识库检索结果]
  ↓
full_context
  ↓
agents.agent_orchestrator.Request
```

### 第 5 步：Intent

文件：`core/intent_recognizer.py`  
函数：`IntentRecognizer.recognize()`，`:118`

它并行/同步综合：

- LLM 识别；
- Embedding 或本地 n-gram；
- 关键词 Pattern；
- LLM 实体提取；
- 紧急度规则。

“401”在技术模板和复合路由技术关键词中。预期主意图是 `technical`，但具体运行结果仍取决于 LLM 和加权分数；不能仅凭静态源码保证每次结果。

### 第 6 步：Agent 选择

文件：`agents/agent_orchestrator.py`  
函数：

- `AgentOrchestrator.run()`，`:247`
- `_collaboration_targets()`，`:334`
- `_route()`，`:316`

对于只有 401、没有账单关键词的消息：

```text
technical target
  ↓
TechnicalAgent
```

不会因为这条消息调用 BillingAgent。

### 第 7 步：Skill 匹配

文件：

- `core/skill_loader.py`
- `skills/technical_support/SKILL.md`

函数：

- `SkillManager.prompt_for()`，`core/skill_loader.py:122`
- `BaseAgent._build_system_prompt()`，`agents/agent_orchestrator.py:156`

匹配原因：

```text
当前 Agent = technical
Skill agents = technical
消息命中关键词 401
```

最终注入“技术支持处理规范”，其中包含 401/403 排查规则和敏感凭证保护要求。

### 第 8 步：LLM

文件：`agents/agent_orchestrator.py`  
函数：`BaseAgent._call_llm()`，`:138`

送给 LLM 的内容：

```text
system:
  TechnicalAgent 固定 system_prompt
  +
  动态技术 Skill

messages:
  [背景信息]
  Memory + RAG
  +
  用户原始问题
```

### 第 9 步：Response 与记忆写回

文件：`api/main.py`  
代码：`:286-304`

```text
TechnicalAgent response
  ↓
Redis 写入 USER 消息
  ↓
Redis 写入 ASSISTANT 消息
  ↓
异步更新 Chroma user_profile
  ↓
ChatResponse
```

完整链路：

```text
用户：登录时报401错误
  ↓
api/main.py:chat()
  ↓
MemoryManager.get_context()
  ↓
_build_knowledge_context()
  ↓
MCPToolManager → knowledge_search → ChromaDB → rerank
  ↓
IntentRecognizer → 单一主意图
  ↓
AgentOrchestrator → TechnicalAgent
  ↓
SkillManager → 技术支持处理规范
  ↓
Technical system prompt + Skill + Memory/RAG context
  ↓
LLM
  ↓
写回 Memory
  ↓
ChatResponse
```

---

## 6. 最终总结

### 6.1 Agent 差异的真正来源

按影响顺序：

1. `agents/agent_orchestrator.py`
   - 不同 Python 子类；
   - 不同 `agent_type`；
   - 不同固定 `system_prompt`。
2. `skills/*/SKILL.md`
   - 不同业务规则、SOP、升级条件和禁止事项。
3. `core/skill_loader.py`
   - 决定哪个 Skill 对哪个 Agent、哪条消息生效。
4. `agents/agent_orchestrator.py`
   - 决定请求被送到哪个 Agent，或是否并行。

不是差异来源：

- LLM 模型：当前共享；
- Tool：当前共享且由 API 主链调用；
- 知识库：当前共享；
- Memory：当前共享同一套管理器；
- 独立 Agent 配置文件：不存在。

### 6.2 当前知识库架构

```text
一套共享 knowledge_base
  ↓
/chat 在 Agent 选择前统一检索
  ↓
Top-K 进入 Request.context
  ↓
一个或多个 Agent 共用
```

没有：

- Technical collection；
- Billing collection；
- Agent metadata filter；
- Agent 专属检索 Tool；
- Agent 自主 tool calling。

当前部署还存在一个运行差异：

```text
设计/Compose：独立 ChromaDB 服务
实际应用：连接失败后使用本地 PersistentClient
独立服务：健康但 collection 为空
```

### 6.3 后续开发最应该关注的文件

|优先级|文件|关注原因|
|-|-|-|
|1|`agents/agent_orchestrator.py`|Agent class、Prompt、路由、并行、降级都在这里|
|2|`api/main.py`|组件初始化、共享 RAG、Agent 调用顺序都在这里|
|3|`core/skill_loader.py`|决定 Skill 匹配和 Prompt 注入|
|4|`skills/*/SKILL.md`|调整各 Agent 的业务行为和安全边界|
|5|`mcp/knowledge_base.py`|知识 collection、切片、默认文档和检索|
|6|`mcp/tool_manager.py`|查询改写、并行召回、缓存、熔断和重排|
|7|`core/intent_recognizer.py`|单主意图识别、投票和实体提取|
|8|`memory/conversation_memory.py`|对话上下文、情景记忆和用户画像|
|9|`docker-compose.yml`、环境配置|排查独立 ChromaDB 健康但应用连接失败的问题|

如果后续目标是让 Agent 真正拥有不同能力，首先需要明确要引入哪一种隔离：

- 不同 Tool 权限；
- 不同知识 collection 或 metadata filter；
- 不同模型/参数；
- 不同真实后台系统；
- 更明确的多 Intent 数据结构；
- 多 Agent 结果汇总 Agent。

这些能力当前源码均未完整实现，不能把现有 Prompt 差异误认为真实工具或数据权限差异。
