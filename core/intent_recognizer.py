"""
亮点：端到端意图识别

三路融合策略：
  1. LLM 语义理解（权重 70%）—— 主力，理解复杂语义和上下文
  2. Embedding 向量相似度（权重 20%）—— 快速匹配常见表达
  3. 关键词模式匹配（权重 10%）—— 零延迟兜底

三路结果通过加权投票合并，置信度低于阈值时降级为 OTHER。
LLM 和 Embedding 并行调用，不串行等待。
"""
import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


class IntentCategory(Enum):
    QUERY      = "query"       # 查询信息
    COMPLAINT  = "complaint"   # 投诉不满
    REQUEST    = "request"     # 请求操作
    GREETING   = "greeting"    # 问候
    ESCALATION = "escalation"  # 要求升级/转人工
    TECHNICAL  = "technical"   # 技术问题
    BUSINESS_ACCOUNT_QUERY = "business_account_query"
    BUSINESS_PLAN_QUERY = "business_plan_query"
    BUSINESS_PLAN_RECOMMENDATION = "business_plan_recommendation"
    BUSINESS_PLAN_CHANGE = "business_plan_change"
    BUSINESS_PLAN_UNSUBSCRIBE = "business_plan_unsubscribe"
    BUSINESS_PRODUCT_QUERY = "business_product_query"
    BUSINESS_DATA_PACK_PURCHASE = "business_data_pack_purchase"
    BUSINESS_VOICE_PACK_PURCHASE = "business_voice_pack_purchase"
    BUSINESS_VAS_ACTIVATION = "business_vas_activation"
    BUSINESS_ACCOUNT_RECHARGE = "business_account_recharge"
    BUSINESS_TRANSACTION_STATUS = "business_transaction_status"
    BUSINESS_BROADBAND_QUERY = "business_broadband_query"
    BUSINESS_MANUAL_SERVICE = "business_manual_service"
    FEEDBACK   = "feedback"    # 正面反馈
    OTHER      = "other"


class UrgencyLevel(Enum):
    LOW      = 1
    MEDIUM   = 2
    HIGH     = 3
    CRITICAL = 4


@dataclass
class IntentResult:
    intent:     IntentCategory
    confidence: float
    urgency:    UrgencyLevel
    entities:   Dict[str, List[str]]   # 从消息中提取的实体
    reasoning:  str
    latency_ms: float


# ── Few-shot 模板（同时用于 LLM 示例和 Embedding 匹配）────────────────────────
_TEMPLATES: Dict[IntentCategory, List[str]] = {
    IntentCategory.QUERY:      ["我的订单状态是什么？", "如何重置密码？", "快递什么时候到？"],
    IntentCategory.COMPLAINT:  ["等了好几个小时！", "服务太差了！", "一直没人处理！"],
    IntentCategory.REQUEST:    ["帮我取消订单", "我需要修改地址", "请协助退款"],
    IntentCategory.GREETING:   ["你好", "嗨，有人吗", "早上好"],
    IntentCategory.ESCALATION: ["我要投诉！", "转人工客服", "找你们经理"],
    IntentCategory.TECHNICAL:  ["应用一直崩溃", "无法登录", "出现500错误"],
    IntentCategory.BUSINESS_ACCOUNT_QUERY: ["我还有多少流量？", "我的余额是多少？", "当前是什么套餐？"],
    IntentCategory.BUSINESS_PLAN_QUERY: ["有哪些Demo套餐？", "59元套餐包含什么？"],
    IntentCategory.BUSINESS_PLAN_RECOMMENDATION: ["我每月需要30GB，有推荐吗？", "想换便宜一点的套餐"],
    IntentCategory.BUSINESS_PLAN_CHANGE: ["帮我换成Demo 79元套餐", "我要变更套餐"],
    IntentCategory.BUSINESS_PLAN_UNSUBSCRIBE: ["我要退订当前套餐"],
    IntentCategory.BUSINESS_PRODUCT_QUERY: ["有哪些流量包？", "有什么语音包？"],
    IntentCategory.BUSINESS_DATA_PACK_PURCHASE: ["给我购买30GB流量包"],
    IntentCategory.BUSINESS_VOICE_PACK_PURCHASE: ["购买300分钟语音包"],
    IntentCategory.BUSINESS_VAS_ACTIVATION: ["开通视频彩铃"],
    IntentCategory.BUSINESS_ACCOUNT_RECHARGE: ["给Demo账户充值100元"],
    IntentCategory.BUSINESS_TRANSACTION_STATUS: ["刚才的办理成功了吗？"],
    IntentCategory.BUSINESS_BROADBAND_QUERY: ["我想了解宽带安装"],
    IntentCategory.BUSINESS_MANUAL_SERVICE: ["我要注销号码", "帮我开国际漫游"],
    IntentCategory.FEEDBACK:   ["服务很棒！", "非常满意", "给个好评"],
}

# 紧急关键词
_URGENCY_KEYWORDS = {
    UrgencyLevel.CRITICAL: ["紧急", "emergency", "urgent", "asap", "立刻"],
    UrgencyLevel.HIGH:     ["今天", "马上", "尽快", "hurry", "now"],
    UrgencyLevel.MEDIUM:   ["这周", "soon", "快点"],
}


def _cosine(a: List[float], b: List[float]) -> float:
    """纯 Python 余弦相似度，不依赖 numpy。"""
    dot = sum(x * y for x, y in zip(a, b))
    na  = sum(x * x for x in a) ** 0.5
    nb  = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


BUSINESS_INTENTS = frozenset(
    intent for intent in IntentCategory if intent.value.startswith("business_")
)


def classify_business_intent(message: str) -> Optional[IntentCategory]:
    """确定性识别首期移动业务，安全相关写请求不依赖 LLM 路由。"""
    msg = re.sub(r"\s+", "", (message or "").lower())
    if not msg:
        return None

    if any(word in msg for word in ("人工客服", "转人工", "投诉")):
        return None

    manual_words = (
        "注销号码", "销户", "新开户", "新手机号", "停机保号", "国际漫游",
        "宽带移机", "迁移宽带", "实名认证", "身份认证", "退款", "重复扣款", "账单争议",
    )
    if any(word in msg for word in manual_words) or (
        "宽带" in msg and any(word in msg for word in ("迁移", "移机", "换地址"))
    ):
        return IntentCategory.BUSINESS_MANUAL_SERVICE

    if "宽带" in msg:
        return IntentCategory.BUSINESS_BROADBAND_QUERY

    if any(word in msg for word in ("刚才办", "刚才买", "办理成功", "购买成功", "交易成功", "交易状态", "处理状态")):
        return IntentCategory.BUSINESS_TRANSACTION_STATUS

    if "充值" in msg or re.search(r"充(?:值)?\d+(?:\.\d+)?元", msg):
        return IntentCategory.BUSINESS_ACCOUNT_RECHARGE

    if any(word in msg for word in ("退订当前套餐", "退订套餐", "取消当前套餐", "取消套餐")):
        return IntentCategory.BUSINESS_PLAN_UNSUBSCRIBE

    action = any(word in msg for word in ("购买", "买", "办理", "开通", "给我开", "帮我开", "帮我换", "换成", "变更为"))
    if action and ("流量包" in msg or re.search(r"\d+(?:\.\d+)?g(?:b)?流量", msg)):
        return IntentCategory.BUSINESS_DATA_PACK_PURCHASE
    if action and ("语音包" in msg or re.search(r"\d+分钟", msg)):
        return IntentCategory.BUSINESS_VOICE_PACK_PURCHASE
    if action and any(word in msg for word in ("视频彩铃", "彩铃", "来电提醒", "增值业务")):
        return IntentCategory.BUSINESS_VAS_ACTIVATION

    if any(word in msg for word in ("更换套餐", "变更套餐", "换套餐", "换成", "就这个套餐", "按这个方案办理")) or (
        "套餐" in msg and any(word in msg for word in ("办理新", "办理一个", "换一个"))
    ):
        return IntentCategory.BUSINESS_PLAN_CHANGE

    if any(word in msg for word in ("推荐套餐", "套餐推荐", "适合我的套餐", "套餐太贵", "便宜一点")) or (
        "套餐" in msg and any(word in msg for word in ("预算", "每月需要", "一个月需要", "推荐"))
    ) or (
        "推荐" in msg and re.search(r"\d+(?:\.\d+)?g(?:b)?", msg)
    ):
        return IntentCategory.BUSINESS_PLAN_RECOMMENDATION

    if any(word in msg for word in ("有什么流量包", "有哪些流量包", "流量包介绍", "有什么语音包", "有哪些语音包", "增值业务有哪些")):
        return IntentCategory.BUSINESS_PRODUCT_QUERY

    if any(word in msg for word in ("有哪些套餐", "有什么套餐", "套餐列表", "套餐详情", "5g套餐")) or (
        "套餐" in msg and any(word in msg for word in ("有哪些", "有什么", "都有什么", "介绍一下"))
    ) or re.search(r"\d+元套餐", msg):
        return IntentCategory.BUSINESS_PLAN_QUERY

    account_phrases = (
        "账户情况", "账户信息", "当前套餐", "现在是什么套餐", "我的套餐", "话费余额",
        "我的余额", "余额还有多少", "还有多少流量", "剩余流量", "流量还剩", "通话分钟还剩", "剩余通话",
    )
    if any(word in msg for word in account_phrases):
        return IntentCategory.BUSINESS_ACCOUNT_QUERY

    if any(word in msg for word in ("流量包", "语音包", "视频彩铃", "来电提醒")):
        return IntentCategory.BUSINESS_PRODUCT_QUERY
    return None


class IntentRecognizer:
    """
    端到端意图识别器。

    初始化时不加载任何本地模型，所有 AI 能力通过 Anthropic API 调用。
    模板 Embedding 在首次请求时懒加载并缓存，后续复用。
    """

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        confidence_threshold: float = 0.5,
    ):
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client    = AsyncAnthropic(**kwargs)
        self.model     = model
        self.threshold = confidence_threshold
        # 第三方兼容 API（如 DeepSeek）通常不支持 Embedding，禁用该策略。
        # 官方 Anthropic SDK 当前没有 embeddings 资源，因此下面会使用稳定的
        # 本地字符 n-gram 向量作为轻量兜底，保证三路融合链路真实可跑。
        self._embedding_enabled = not bool(base_url)

        self._tpl_embeddings: Dict[IntentCategory, List[List[float]]] = {}
        self._cache: Dict[str, IntentResult] = {}
        self.cache_hits   = 0
        self.cache_misses = 0

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    async def recognize(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> IntentResult:
        """
        识别用户意图。

        history 格式：[{"role": "user"/"assistant", "content": "..."}]
        """
        key = self._cache_key(message)
        if key in self._cache:
            self.cache_hits += 1
            return self._cache[key]
        self.cache_misses += 1

        t0 = time.monotonic()

        business_intent = classify_business_intent(message)
        if business_intent is not None:
            result = IntentResult(
                intent=business_intent,
                confidence=0.99,
                urgency=self._urgency(message, business_intent),
                entities={},
                reasoning="命中已确认的移动业务确定性路由规则",
                latency_ms=(time.monotonic() - t0) * 1000,
            )
            self._cache[key] = result
            return result

        # LLM 和 Embedding 并行（Embedding 不可用时跳过）
        llm_task = asyncio.create_task(self._llm_recognize(message, history))
        emb_task = asyncio.create_task(self._embedding_recognize(message)) if self._embedding_enabled else None
        pat      = self._pattern_recognize(message)

        if emb_task:
            llm, emb = await asyncio.gather(llm_task, emb_task)
        else:
            llm = await llm_task
            emb = {"intent": IntentCategory.OTHER, "confidence": 0.0}

        intent = self._vote(llm, emb, pat)
        entities = await self._extract_entities(message)
        urgency  = self._urgency(message, intent)

        result = IntentResult(
            intent=intent,
            confidence=llm["confidence"],
            urgency=urgency,
            entities=entities,
            reasoning=llm.get("reasoning", ""),
            latency_ms=(time.monotonic() - t0) * 1000,
        )

        # LRU 缓存
        if len(self._cache) >= 1000:
            for k in list(self._cache)[:500]:
                del self._cache[k]
        self._cache[key] = result
        return result

    def learn(self, message: str, correct: IntentCategory) -> None:
        """在线学习：将纠正样本加入模板，清除对应 Embedding 缓存。"""
        tpls = _TEMPLATES.setdefault(correct, [])
        if message not in tpls:
            tpls.append(message)
            self._tpl_embeddings.pop(correct, None)  # 下次重新计算
            logger.info(f"学习新样本 → {correct.value}: {message[:40]}")

    # ── 三路识别策略 ──────────────────────────────────────────────────────────

    async def _llm_recognize(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]],
    ) -> Dict[str, Any]:
        """策略 1：LLM 语义理解（Few-shot + 上下文）。"""
        message = self._clean_text(message)
        # 构建 Few-shot 示例
        examples = "\n".join(
            f'  消息: "{t}" → 意图: {cat.value}'
            for cat, tpls in _TEMPLATES.items()
            for t in tpls[:1]  # 每类取 1 条，控制 prompt 长度
        )
        # 最近 3 轮对话上下文
        ctx = ""
        if history:
            ctx = "\n最近对话:\n" + "\n".join(
                f"  {self._clean_text(m.get('role', 'user'))}: {self._clean_text(m.get('content', ''))}"
                for m in history[-3:]
            )

        prompt = f"""你是客服意图分析专家。根据示例判断用户意图，返回 JSON。

示例:
{examples}

{ctx}
用户消息: "{message}"

返回格式（仅 JSON，不要其他文字）:
{{"intent": "<意图值>", "confidence": <0-1>, "reasoning": "<一句话说明>"}}

可选意图: {", ".join(c.value for c in IntentCategory)}"""
        prompt = self._clean_text(prompt)

        try:
            resp = await self.client.messages.create(
                model=self.model,
                max_tokens=256,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
            s, e = raw.find("{"), raw.rfind("}") + 1
            data = json.loads(raw[s:e])
            try:
                data["intent"] = IntentCategory(data["intent"])
            except ValueError:
                data["intent"] = IntentCategory.OTHER
            return data
        except Exception as ex:
            logger.warning(f"LLM 识别失败: {ex}")
            return {"intent": IntentCategory.OTHER, "confidence": 0.0, "reasoning": "LLM 失败", "failed": True}

    async def _embedding_recognize(self, message: str) -> Dict[str, Any]:
        """策略 2：Embedding 向量相似度匹配。"""
        try:
            await self._load_template_embeddings()
            msg_vec = await self._embed_text(message)

            best_cat, best_score = IntentCategory.OTHER, 0.0
            for cat, vecs in self._tpl_embeddings.items():
                score = max(_cosine(msg_vec, v) for v in vecs)
                if score > best_score:
                    best_score, best_cat = score, cat

            return {"intent": best_cat, "confidence": best_score}
        except Exception as ex:
            logger.warning(f"Embedding 识别失败: {ex}")
            return {"intent": IntentCategory.OTHER, "confidence": 0.0}

    def _pattern_recognize(self, message: str) -> Dict[str, Any]:
        """策略 3：关键词模式匹配（同步，零延迟兜底）。"""
        msg = message.lower()
        patterns = {
            IntentCategory.ESCALATION: ["投诉", "经理", "转人工", "supervisor"],
            IntentCategory.COMPLAINT:  ["太差", "糟糕", "horrible", "等了很久"],
            IntentCategory.QUERY:      ["?", "？", "怎么", "什么", "status"],
            IntentCategory.REQUEST:    ["帮我", "需要", "please", "help"],
            IntentCategory.GREETING:   ["你好", "嗨", "hello", "hi"],
            IntentCategory.TECHNICAL:  ["崩溃", "报错", "error", "crash"],
        }
        best_cat, best_score = IntentCategory.OTHER, 0.0
        for cat, kws in patterns.items():
            hits = sum(1 for kw in kws if kw in msg)
            if hits:
                score = hits / len(kws)
                if score > best_score:
                    best_score, best_cat = score, cat
        return {"intent": best_cat, "confidence": best_score}

    # ── 投票合并 ──────────────────────────────────────────────────────────────

    def _vote(self, llm: Dict, emb: Dict, pat: Dict) -> IntentCategory:
        """加权投票。embedding 不可用时权重自动转移到 LLM 和 Pattern。"""
        if llm.get("failed"):
            if emb.get("intent") != IntentCategory.OTHER and emb.get("confidence", 0.0) > 0:
                return emb["intent"]
            if pat.get("intent") != IntentCategory.OTHER and pat.get("confidence", 0.0) > 0:
                return pat["intent"]
            return IntentCategory.OTHER

        if self._embedding_enabled:
            weights = [(llm, 0.7), (emb, 0.2), (pat, 0.1)]
        else:
            weights = [(llm, 0.85), (pat, 0.15)]
        scores: Dict[IntentCategory, float] = {}
        for result, w in weights:
            cat  = result.get("intent", IntentCategory.OTHER)
            conf = result.get("confidence", 0.0)
            scores[cat] = scores.get(cat, 0.0) + w * conf

        best = max(scores, key=scores.get)  # type: ignore
        return best if scores[best] >= self.threshold else IntentCategory.OTHER

    # ── 实体提取 ──────────────────────────────────────────────────────────────

    async def _extract_entities(self, message: str) -> Dict[str, List[str]]:
        """用 LLM 从消息中提取结构化实体。"""
        message = self._clean_text(message)
        prompt = f"""从客服消息中提取实体，返回 JSON（字段值为列表，没有则为空列表）:
消息: "{message}"
格式: {{"order_id":[],"product":[],"date":[],"amount":[],"error_code":[]}}"""
        prompt = self._clean_text(prompt)
        try:
            resp = await self.client.messages.create(
                model=self.model, max_tokens=256, temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
            s, e = raw.find("{"), raw.rfind("}") + 1
            return json.loads(raw[s:e])
        except Exception:
            return {"order_id": [], "product": [], "date": [], "amount": [], "error_code": []}

    # ── 辅助 ──────────────────────────────────────────────────────────────────

    async def _load_template_embeddings(self) -> None:
        """懒加载所有模板的 Embedding（只在首次调用时执行）。"""
        missing = [cat for cat in _TEMPLATES if cat not in self._tpl_embeddings]
        if not missing:
            return

        all_texts = [t for cat in missing for t in _TEMPLATES[cat]]
        vecs = [await self._embed_text(text) for text in all_texts]
        idx = 0
        for cat in missing:
            n = len(_TEMPLATES[cat])
            self._tpl_embeddings[cat] = vecs[idx: idx + n]
            idx += n

    async def _embed_text(self, text: str) -> List[float]:
        """
        生成文本向量。

        如果未来接入的官方/兼容客户端提供 embeddings.create，会优先使用远端向量；
        当前 Anthropic SDK 没有该资源时，退化为字符 n-gram 哈希向量。这样不会因为
        Embedding 服务缺失导致三路融合中断。
        """
        embeddings = getattr(self.client, "embeddings", None)
        if embeddings is not None:
            try:
                resp = await embeddings.create(model="voyage-3-lite", input=[text])
                return list(resp.data[0].embedding)
            except Exception as ex:
                logger.warning(f"远端 Embedding 失败，使用本地向量兜底: {ex}")

        return self._local_embedding(text)

    @staticmethod
    def _local_embedding(text: str, dims: int = 256) -> List[float]:
        """稳定的字符 n-gram 哈希向量，用于无远端 Embedding 时的语义近似匹配。"""
        normalized = text.lower().strip()
        vec = [0.0] * dims
        tokens = set()
        for n in (1, 2, 3):
            if len(normalized) >= n:
                tokens.update(normalized[i:i + n] for i in range(len(normalized) - n + 1))
        if not tokens:
            tokens.add(normalized)

        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % dims
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        return vec

    def _urgency(self, message: str, intent: IntentCategory) -> UrgencyLevel:
        msg = message.lower()
        for level, kws in _URGENCY_KEYWORDS.items():
            if any(kw in msg for kw in kws):
                return level
        if intent == IntentCategory.ESCALATION:
            return UrgencyLevel.HIGH
        if intent == IntentCategory.COMPLAINT:
            return UrgencyLevel.MEDIUM
        return UrgencyLevel.LOW

    def _cache_key(self, message: str) -> str:
        return self._clean_text(message)[:200]

    @staticmethod
    def _clean_text(value: Any) -> str:
        """移除 Unicode 代理字符，避免 HTTP 客户端编码 prompt 时崩溃。"""
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        return value.encode("utf-8", errors="ignore").decode("utf-8")

    @property
    def cache_stats(self) -> Dict[str, Any]:
        total = self.cache_hits + self.cache_misses
        return {
            "size": len(self._cache),
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "hit_rate": self.cache_hits / total if total else 0.0,
        }
