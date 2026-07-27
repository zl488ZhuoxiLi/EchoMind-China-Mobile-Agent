```markdown id="zbxzzb"
# CODEX_GUIDE.md

## 0. Purpose

This file is the global navigation and coding contract for EchoMind.

Before modifying code:

1. Read this file.
2. Inspect the relevant existing source files.
3. Treat the current repository, `requirements.txt`, `docker-compose.yml`, `.env.example`, and existing API models as the final implementation truth.
4. Do not invent dependencies, APIs, directories, configuration fields, or architectural behavior that do not exist in the repository.

---

# 1. Project Definition

**EchoMind is an enterprise-grade LLM customer-service system built around FastAPI, multi-Agent orchestration, RAG, Redis + ChromaDB memory, dynamic Skills, reliable tool calling, online monitoring, and LLM-as-Judge evaluation.**

Core goal:

```text
User Request
→ Memory + RAG Context
→ Intent Recognition
→ Agent Routing
→ Dynamic Skills Injection
→ LLM Response
→ Memory Update
→ Monitoring / Evaluation Feedback
```

The project is not a generic chatbot. Preserve its Agent, RAG, memory, Skills, monitoring, and evaluation architecture.

---

# 2. Technology Stack and Version Rules

## 2.1 Runtime

| Component | Constraint |
|---|---|
| Python | **3.12** |
| API framework | FastAPI |
| ASGI server | Uvicorn |
| LLM | Anthropic API or Anthropic-compatible API such as DeepSeek |
| Short-term memory | Redis |
| Vector storage | ChromaDB |
| Monitoring | Prometheus |
| Reverse proxy | Nginx |
| Deployment | Docker + Docker Compose |

## 2.2 Dependency Version Policy

The project documents do **not** specify exact package version numbers other than the Python 3.12 runtime.

Therefore:

```text id="6k01xo"
Python package versions → requirements.txt is the only source of truth
Container/image versions → docker-compose.yml / Dockerfile are the only source of truth
Environment variables → .env.example is the primary source of truth
```

Mandatory rules:

- NEVER guess a library version.
- NEVER upgrade/downgrade a dependency without an explicit task.
- NEVER introduce a new dependency when the existing stack can solve the problem.
- Before using a third-party API, inspect the installed package version and existing project usage.
- Preserve compatibility with the current `requirements.txt`.

## 2.3 Important Environment Variables

Documented variables include:

```text id="9s5e9r"
ANTHROPIC_API_KEY
ANTHROPIC_BASE_URL
ANTHROPIC_MODEL

REDIS_URL
REDIS_PASSWORD

CHROMA_HOST
CHROMA_PORT
CHROMA_PERSIST_DIRECTORY

ECHOMIND_SKILLS_DIR
ECHOMIND_SKILLS_MAX_PROMPT_CHARS
```

Never hard-code API keys, passwords, or secrets.

## 2.4 Default Service Ports

```text id="6l1miq"
EchoMind API : 8000
Nginx        : 80
Redis        : 6379
ChromaDB     : 8001 on host
Prometheus   : 9090
```

Container-network addresses may differ from host addresses. Always inspect `docker-compose.yml` before changing connection configuration.

---

# 3. Directory Structure

Do not create alternative architecture unless explicitly requested.

```text id="692r9b"
EchoMind/
│
├── api/
│   └── main.py
│       FastAPI application entry.
│       Owns HTTP endpoints and application initialization.
│
├── core/
│   ├── intent_recognizer.py
│   │   LLM + Embedding + Pattern intent recognition.
│   │
│   └── skill_loader.py
│       Loads, filters and renders dynamic Skills.
│
├── agents/
│   └── agent_orchestrator.py
│       Agent definitions, routing, collaboration,
│       performance routing and fallback.
│
├── memory/
│   └── conversation_memory.py
│       Redis working memory.
│       ChromaDB episodic memory.
│       ChromaDB user profile.
│
├── mcp/
│   ├── tool_manager.py
│   │   Tool registration and execution.
│   │   Cache / timeout / circuit breaker / fallback.
│   │   Query rewrite / parallel recall / reranking.
│   │
│   └── knowledge_base.py
│       ChromaDB RAG knowledge base.
│
├── monitor/
│   └── performance_monitor.py
│       Agent/Tool metrics collection.
│       Computes penalties and feeds them back into routing.
│
├── evaluation/
│   └── evaluator.py
│       Intent evaluation.
│       Real end-to-end Agent evaluation.
│       LLM-as-Judge.
│       Regression detection and recommendations.
│
├── skills/
│   ├── general_customer_service/
│   │   └── SKILL.md
│   │
│   ├── technical_support/
│   │   └── SKILL.md
│   │
│   └── billing_support/
│       └── SKILL.md
│
├── data/
│   ├── demo_docs/
│   │   ├── sample_knowledge.json
│   │   └── troubleshooting.md
│   │
│   └── eval/
│       └── baseline.json
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── .env                 # local only; never commit secrets
```

IMPORTANT:

If the real repository differs from this documented tree, **inspect the repository first and preserve the existing implementation**. Do not move files merely to make the tree match this guide.

---

# 4. Core Architecture

## 4.1 `/chat` Main Flow

Expected logical flow:

```text id="t0et1c"
POST /chat
    │
    ▼
api/main.py
    │
    ├─ MemoryManager.get_context()
    │      ├─ Redis working memory
    │      ├─ ChromaDB episodic
    │      └─ ChromaDB user_profile
    │
    ├─ Knowledge/RAG context
    │      ▼
    │   MCPToolManager.search_with_rewrite()
    │      ├─ query rewrite
    │      ├─ parallel ChromaDB recall
    │      ├─ deduplication
    │      └─ LLM reranking
    │
    ├─ AgentOrchestrator.run()
    │      │
    │      ├─ IntentRecognizer.recognize()
    │      │      ├─ LLM
    │      │      ├─ Embedding
    │      │      └─ Pattern
    │      │
    │      ├─ composite-problem detection
    │      ├─ Agent routing
    │      ├─ optional parallel Agent execution
    │      └─ fallback
    │
    ├─ Agent builds system prompt
    │      ▼
    │   SkillManager.prompt_for(message, agent_type)
    │
    ├─ LLM response
    │
    ├─ MemoryManager.add_message()
    │      ├─ user message
    │      └─ assistant response
    │
    └─ async MemoryManager.update_profile()
           ▼
        ChromaDB user_profile
```

Do not bypass these layers without an explicit architectural task.

---

# 5. Core Modules

## 5.1 Intent Recognition

File:

```text id="js3ca4"
core/intent_recognizer.py
```

Documented design:

```text id="pmz95l"
LLM semantic recognition
        +
Embedding similarity
        +
Pattern keyword matching
        ↓
weighted voting
        ↓
intent + confidence + urgency + entities
```

Official API mode:

```text id="wxqa2h"
LLM       70%
Embedding 20%
Pattern   10%
```

Third-party compatible API mode:

```text id="87rs25"
LLM       85%
Embedding disabled
Pattern   15%
```

Low-confidence results fall back to `OTHER`.

Do not replace this with keyword-only or LLM-only routing.

---

## 5.2 Agent Orchestration

File:

```text id="y68r9c"
agents/agent_orchestrator.py
```

Primary Agents:

```text id="7woup8"
GeneralAgent
TechnicalAgent
BillingAgent
```

Routing intent:

```text id="kktwni"
technical       → TechnicalAgent
billing/account → BillingAgent
other           → GeneralAgent
escalation      → escalation state
```

Composite requests may execute multiple Agents in parallel.

Example:

```text id="bn72cp"
"登录报错 401，而且这个月还重复扣款了"

→ TechnicalAgent
+ BillingAgent
```

Routing also considers Agent runtime performance.

Conceptually:

```text id="x2vqqs"
base_score =
    success_rate * 0.7
    + latency_score * 0.3

routing_score =
    base_score * (1 - monitor_penalty)
```

Preserve fallback to GeneralAgent when specialist execution is unavailable or fails.

---

## 5.3 Dynamic Skills

Files:

```text id="ljdceh"
core/skill_loader.py
skills/*/SKILL.md
```

Skills define **how customer service should handle a situation**.

Knowledge base defines **business facts**.

Do not merge these concepts.

Selection order:

```text id="q6smct"
enabled?
    ↓
agent type matches?
    ↓
keyword matches?
    ↓
render Skill
    ↓
inject into system prompt
```

Agent isolation:

```text id="rf85c6"
general   → general customer-service rules
technical → technical-support rules
billing   → billing/refund rules
```

Do NOT hard-code frequently changing SOP/business rules into Agent source code when they belong in Skills.

Skills must remain reloadable through the existing reload mechanism.

---

## 5.4 RAG / Knowledge Base

Files:

```text id="x1jppt"
mcp/tool_manager.py
mcp/knowledge_base.py
```

Collection:

```text id="jq45o1"
knowledge_base
```

Retrieval pipeline:

```text id="xazp9t"
original query
→ LLM query rewrite
→ multiple subqueries
→ parallel recall
→ merge
→ deduplicate
→ LLM rerank
→ Top-K
```

Knowledge retrieval is part of `/chat`, not merely a standalone `/search` demo.

Do not directly call ChromaDB from random Agent code when the operation belongs behind the existing knowledge/tool abstraction.

---

## 5.5 Tool Reliability

Tool execution must preserve the existing reliability chain:

```text id="q8zw30"
cache check
→ circuit-breaker check
→ parameter validation
→ timeout
→ handler
→ statistics update
→ cache
→ fallback on failure
```

When modifying tools:

- Preserve JSON-schema/parameter validation if currently implemented.
- Preserve timeout behavior.
- Preserve ToolStats.
- Preserve circuit-breaker state.
- Preserve fallback behavior.
- Do not allow one failed external dependency to crash the entire `/chat` request when an existing fallback path applies.

---

# 6. Storage Rules

## 6.1 Redis

Purpose:

```text id="oqkgux"
short-term working memory
```

Documented key:

```text id="abmzal"
wm:{user_id}:{conv_id}
```

Summary key:

```text id="y305fk"
summary:{user_id}:{conv_id}
```

Documented TTL:

```text id="hvup0k"
24 hours
```

Documented memory thresholds:

```text id="kwb1fa"
WORKING_MAX = 20
COMPRESS_AT = 15
```

When compression occurs:

```text id="zj3nt0"
old messages
→ LLM summary
→ Redis summary
→ ChromaDB episodic

working memory
→ retain recent messages
```

Do not use Redis as the permanent RAG knowledge store.

---

## 6.2 ChromaDB

Keep collections logically isolated:

```text id="ablrk1"
knowledge_base
    enterprise knowledge / RAG

episodic
    compressed historical conversation memory

user_profile
    user preferences and extracted entities
```

Never mix customer memory into `knowledge_base`.

Never mix enterprise knowledge into `user_profile`.

---

# 7. Monitoring and Evaluation

## 7.1 Online Monitoring

File:

```text id="cglpdg"
monitor/performance_monitor.py
```

Monitor consumes Agent/Tool statistics and can write a routing penalty back to the Orchestrator.

Closed loop:

```text id="oqca5m"
Agent / Tool execution
→ AgentStats / ToolStats
→ PerformanceMonitor
→ monitor_penalty
→ Orchestrator routing_score
→ future routing changes
```

Monitoring is therefore part of routing behavior, not merely visualization.

---

## 7.2 End-to-End Evaluation

File:

```text id="7coy5i"
evaluation/evaluator.py
```

HTTP entry:

```text id="q58k35"
POST /eval/run
```

Evaluation must use the real orchestration path.

```text id="lgmphd"
evaluation case
→ AgentOrchestrator.run()
→ actual response
→ LLM-as-Judge
→ metrics
→ baseline comparison
→ regression detection
→ recommendations
```

Intent metrics:

```text id="4633ng"
Accuracy
Macro-F1
```

Response quality dimensions:

```text id="x09na6"
relevance
accuracy
completeness
helpfulness
```

Do not replace real Agent execution with a mock unless a specific test explicitly requires mocking.

---

# 8. API Contract Rules

Known public endpoints include:

```text id="a28wrd"
GET  /health
POST /chat

POST /search

POST /knowledge/add
POST /knowledge/upload
GET  /knowledge/stats

GET  /skills
POST /skills/reload

GET  /monitor

POST /eval/run

GET  /docs
```

Mandatory rules:

1. Inspect the current Pydantic/request/response models before editing an endpoint.
2. Preserve existing field names and response types.
3. Do not invent a new global response envelope such as:

   ```json
   {"code": 0, "message": "ok", "data": {}}
   ```

   unless the repository already uses it.

4. Do not silently remove response fields.
5. Keep existing HTTP status-code semantics.
6. Use the project's existing exception pattern at API boundaries.

For `/chat`, preserve the current `ChatRequest` / `ChatResponse` contract defined in source.

---

# 9. Codex Mandatory Coding Rules

## 9.1 Before Writing Code

For every task:

```text id="tjm3o1"
1. Locate relevant files.
2. Read the complete existing implementation.
3. Trace callers and callees.
4. Check requirements/config/API models.
5. Make the smallest architecture-compatible change.
```

Never rewrite a complete subsystem because a local change is sufficient.

---

## 9.2 Dependency Rules

DO:

```text id="q4vylg"
use existing project dependencies
reuse existing abstractions
follow existing imports and patterns
```

DO NOT:

```text id="hi6397"
invent package APIs
add frameworks without approval
change requirements.txt casually
upgrade packages while fixing unrelated bugs
```

---

## 9.3 Async Rules

The project uses async I/O.

For LLM, tools, memory or network operations:

- Preserve `async` / `await`.
- Preserve concurrent execution where already designed.
- Do not introduce blocking network calls into the FastAPI request path.
- Preserve parallel recall with `asyncio.gather()` where applicable.
- Preserve asynchronous user-profile updates when currently implemented.

---

## 9.4 Error Handling

Never use silent exception swallowing:

```python id="uahk0n"
try:
    ...
except Exception:
    pass
```

Preferred behavior:

```text id="0uqw31"
catch the narrowest useful exception
→ log useful context
→ preserve existing fallback
→ expose an appropriate API/tool error
```

Rules:

- Never log API keys or passwords.
- Never expose secrets in API errors.
- Tool failures should use existing fallback/circuit-breaker paths.
- API initialization failures should remain observable.
- Do not convert every exception into a successful response.

---

## 9.5 Logging

Logs should help answer:

```text id="8bwk35"
which module failed?
which Agent/tool?
which request stage?
how long did it take?
was fallback used?
```

Never log secret credentials.

Do not add noisy per-token/per-loop debug logging to production paths.

---

## 9.6 Comments and Docstrings

Use comments only when they explain:

```text id="crzzhk"
WHY the code exists
WHY concurrency/fallback is required
WHY an architectural boundary must remain
```

Do not comment obvious syntax.

Follow the language/style already used in the surrounding file.

Do not add duplicated Chinese + English comments merely for decoration.

---

## 9.7 Architecture Boundaries

Never bypass these boundaries casually:

```text id="39oi8i"
Intent logic       → core/intent_recognizer.py
Agent routing      → agents/agent_orchestrator.py
Skill loading      → core/skill_loader.py
conversation memory→ memory/conversation_memory.py
tool reliability   → mcp/tool_manager.py
knowledge storage  → mcp/knowledge_base.py
online monitoring  → monitor/performance_monitor.py
evaluation         → evaluation/evaluator.py
HTTP composition   → api/main.py
```

If functionality belongs to an existing module, extend that module instead of duplicating logic elsewhere.

---

## 9.8 Security

Never:

```text id="ufibto"
commit .env
hard-code API keys
print API keys
return API keys in errors
store secrets in Skills
```

Preserve customer-service safety rules already encoded in Skills, including sensitive-information boundaries.

---

# 10. Definition of Done

A task is not complete merely because code compiles.

Before declaring completion:

```text id="dqllb6"
[ ] Relevant source files were inspected.
[ ] No undocumented dependency was introduced.
[ ] Existing API contracts remain compatible.
[ ] Existing async behavior was preserved.
[ ] Failure/fallback paths were considered.
[ ] Secrets are not exposed.
[ ] Existing tests were run if the repository provides them.
[ ] Relevant endpoint or module was smoke-tested.
[ ] Changes were summarized by file and behavior.
```

If the repository contains no test command, report that fact. Do not invent one.

---

# 11. Phase 1 TODO — Obtain a Stable Runnable Baseline

Goal:

```text id="kctwqk"
Do not redesign EchoMind yet.
First prove the existing source can run and establish a reproducible baseline.
```

If an item already exists, **verify it instead of rewriting it**.

## P1-01 Repository Inventory

```text id="dsay6r"
[ ] Read requirements.txt
[ ] Read docker-compose.yml
[ ] Read Dockerfile
[ ] Read .env.example
[ ] Confirm documented core directories exist
[ ] Report discrepancies; do not automatically restructure
```

Acceptance:

```text id="cjoiqm"
Codex can state the actual Python dependencies,
container services, environment variables and entrypoint.
```

---

## P1-02 Environment Configuration Check

```text id="vdwruq"
[ ] Confirm Python runtime expectation is 3.12
[ ] Confirm required LLM environment variables
[ ] Confirm Redis configuration
[ ] Confirm ChromaDB configuration
[ ] Confirm Skills directory configuration
[ ] Ensure .env is ignored/not committed
```

Do not print secret values.

---

## P1-03 Docker Baseline

Expected services:

```text id="oynbym"
EchoMind API
Redis
ChromaDB
Prometheus
Nginx
```

Verification target:

```bash id="z8byv5"
docker compose up -d --build
docker compose ps
```

Do not change Compose configuration unless a concrete startup error requires it.

---

## P1-04 API Startup Smoke Test

Verify:

```text id="oij6uy"
GET /health
GET /docs
```

Expected goal:

```text id="poaez4"
FastAPI initializes successfully
and reports the service ready.
```

---

## P1-05 Minimal `/chat` Main Chain

Trace and verify:

```text id="jmo6sd"
/chat
→ memory context
→ RAG context
→ orchestrator
→ intent recognition
→ Agent
→ Skills
→ LLM
→ memory write
```

Smoke-test at least:

```text id="0kjvw7"
general request
technical request
billing request
```

Do not optimize behavior yet.

---

## P1-06 RAG Smoke Test

Verify:

```text id="oklavv"
GET  /knowledge/stats
POST /search
```

Then verify the demo knowledge files can be imported using the existing API.

Acceptance:

```text id="rn4w5j"
knowledge_base contains documents
and search returns results.
```

---

## P1-07 Skills Smoke Test

Verify:

```text id="q94bzm"
GET  /skills
POST /skills/reload
```

Confirm the documented Skill groups load correctly:

```text id="11zmys"
general_customer_service
technical_support
billing_support
```

Confirm Agent filtering remains effective.

---

## P1-08 Baseline Report

After P1-01 through P1-07, produce a concise report:

```text id="6rn7ou"
1. Environment status
2. Container status
3. API status
4. /chat status
5. RAG status
6. Skills status
7. Any failures
8. Exact file/error responsible for each failure
```

Do not begin architecture refactoring until this baseline is complete.

---

# 12. Future Phases — Do Not Execute Yet

```text id="k11fbs"
Phase 2
→ Intent recognition deep verification

Phase 3
→ Multi-Agent routing / parallel collaboration / fallback

Phase 4
→ Redis + ChromaDB memory compression and user profile

Phase 5
→ MCP reliability / RAG rewrite / reranking

Phase 6
→ Dynamic Skills customization

Phase 7
→ Monitor routing-feedback loop

Phase 8
→ LLM-as-Judge evaluation and regression testing

Phase 9
→ Optimization, refactoring and production hardening
```

Only work on a future phase when explicitly assigned.

---

# 13. Final Principle

When uncertain:

```text id="l2pqsg"
DO NOT GUESS.
```

Instead:

```text id="qqi0cg"
inspect source
→ inspect config
→ inspect dependency version
→ inspect caller/callee
→ report uncertainty
→ ask for architectural clarification when necessary
```

The priority order is:

```text id="9jfjdz"
correct architecture
> backward compatibility
> reliability
> readability
> minimal change
> clever implementation
```
```

依据：部署与环境约束来自《EchoMind小白从0到1部署》和《完整使用指南》；主链路、Agent、Skills、RAG、三级记忆、监控及评测行为来自代码讲解、业务流程和技术亮点文档。fileciteturn0file0 fileciteturn0file1 fileciteturn0file3 fileciteturn0file4 fileciteturn0file5
