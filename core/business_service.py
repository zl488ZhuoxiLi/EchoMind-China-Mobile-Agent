"""BusinessAgent 的确定性业务编排和响应层。"""

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.intent_recognizer import IntentCategory, classify_business_intent
from mcp.mock_crm import BusinessAuthContext, ConfirmationStore, MockCRMBackend
from mcp.tool_manager import MCPToolManager


@dataclass
class BusinessServiceResult:
    content: str
    intent: IntentCategory
    success: bool = True
    escalated: bool = False


class BusinessService:
    CONFIRM_PHRASES = {
        "确认办理", "确定购买", "帮我办理", "就这个套餐", "按这个方案办理",
        "开通这个业务", "购买", "确认购买", "确认开通", "确认", "确定",
    }
    CANCEL_PHRASES = {"取消", "不办理", "不买了", "先不要", "算了", "再看看", "否", "不要"}

    BUSINESS_LABELS = {
        "data_pack": "流量包",
        "voice_pack": "语音包",
        "vas": "增值业务",
    }

    def __init__(self, tools: MCPToolManager, backend: MockCRMBackend, confirmations: ConfirmationStore):
        self.tools = tools
        self.backend = backend
        self.confirmations = confirmations

    async def authenticate_header(self, authorization: Optional[str]) -> BusinessAuthContext:
        if not authorization:
            return BusinessAuthContext(False, error_code="AUTH_REQUIRED")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return BusinessAuthContext(False, error_code="INVALID_TOKEN")
        return await self.backend.authenticate(token.strip())

    @staticmethod
    def _normalize_reply(message: str) -> str:
        return re.sub(r"[\s，。！？!?,.]", "", (message or "").lower())

    def is_confirmation_reply(self, message: str) -> bool:
        normalized = self._normalize_reply(message)
        return normalized in self.CONFIRM_PHRASES

    async def has_pending(self, auth: BusinessAuthContext, conv_id: str) -> bool:
        return bool(auth.authenticated and auth.user_id and await self.confirmations.get_pending(auth.user_id, conv_id))

    @staticmethod
    def _context(auth: BusinessAuthContext, conv_id: str, request_id: str) -> Dict[str, Any]:
        return {
            "authenticated": auth.authenticated,
            "authenticated_user_id": auth.user_id,
            "conv_id": conv_id,
            "request_id": request_id,
            "demo": True,
        }

    async def handle(self, req: Any) -> BusinessServiceResult:
        auth: BusinessAuthContext = req.auth_context or BusinessAuthContext(False, error_code="AUTH_REQUIRED")
        context = self._context(auth, req.conv_id, req.request_id)

        if auth.authenticated and auth.user_id:
            pending = await self.confirmations.get_pending(auth.user_id, req.conv_id)
            if pending:
                pending_result = await self._handle_pending(req.message, auth, req.conv_id, context, pending)
                if pending_result is not None:
                    return pending_result

        if self.is_confirmation_reply(req.message):
            return BusinessServiceResult(
                "当前没有可执行的待确认 Demo 业务，可能已超时或已处理。请重新选择业务。",
                IntentCategory.BUSINESS_TRANSACTION_STATUS,
            )

        intent = req.intent or classify_business_intent(req.message) or IntentCategory.BUSINESS_PLAN_QUERY

        if intent == IntentCategory.BUSINESS_MANUAL_SERVICE:
            return BusinessServiceResult(
                "该业务当前必须由人工处理。当前为 Demo 人工介入标记，未创建真实工单。",
                intent,
                escalated=True,
            )
        if intent == IntentCategory.BUSINESS_BROADBAND_QUERY:
            return BusinessServiceResult(
                "当前 Demo 可介绍宽带安装和升级流程，但不执行宽带办理；宽带移机必须转人工。"
                "实际覆盖、资费和预约需要以当地渠道核验结果为准。",
                intent,
            )
        if intent == IntentCategory.BUSINESS_ACCOUNT_QUERY:
            return await self._account_summary(intent, context)
        if intent == IntentCategory.BUSINESS_PLAN_QUERY:
            return await self._plan_query(req.message, intent, context)
        if intent == IntentCategory.BUSINESS_PLAN_RECOMMENDATION:
            return await self._recommend_plan(req.message, req.conv_id, intent, context)
        if intent == IntentCategory.BUSINESS_PRODUCT_QUERY:
            return await self._product_query(req.message, intent, context)
        if intent == IntentCategory.BUSINESS_TRANSACTION_STATUS:
            return await self._transaction_status(intent, context)

        if intent in {
            IntentCategory.BUSINESS_PLAN_CHANGE,
            IntentCategory.BUSINESS_PLAN_UNSUBSCRIBE,
            IntentCategory.BUSINESS_DATA_PACK_PURCHASE,
            IntentCategory.BUSINESS_VOICE_PACK_PURCHASE,
            IntentCategory.BUSINESS_VAS_ACTIVATION,
            IntentCategory.BUSINESS_ACCOUNT_RECHARGE,
        }:
            if not auth.authenticated:
                return BusinessServiceResult("该操作需要先提供有效的 Demo Mock Token。", intent, success=False)
            return await self._prepare_write(req.message, req.conv_id, intent, context)

        return BusinessServiceResult("请说明您想查询套餐、购买资源包，还是办理具体移动业务。", intent)

    async def _handle_pending(self, message: str, auth: BusinessAuthContext, conv_id: str,
                              context: Dict[str, Any], pending: Dict[str, Any]) -> Optional[BusinessServiceResult]:
        normalized = self._normalize_reply(message)
        pending_intent = self._pending_intent(pending)
        if normalized in self.CANCEL_PHRASES:
            await self.confirmations.cancel(auth.user_id or "", conv_id)
            return BusinessServiceResult("已取消本次 Demo 办理，不会扣费或变更账户。",
                                         pending_intent)
        if normalized in self.CONFIRM_PHRASES:
            confirmed = await self.confirmations.confirm(auth.user_id or "", conv_id)
            if not confirmed:
                return BusinessServiceResult("确认上下文已失效，请重新选择业务并确认。",
                                             pending_intent, success=False)
            return await self._execute_confirmed(confirmed, context)

        new_intent = classify_business_intent(message)
        if new_intent is not None:
            await self.confirmations.cancel(auth.user_id or "", conv_id)
            if new_intent in {IntentCategory.BUSINESS_PLAN_CHANGE,
                              IntentCategory.BUSINESS_DATA_PACK_PURCHASE,
                              IntentCategory.BUSINESS_VOICE_PACK_PURCHASE,
                              IntentCategory.BUSINESS_VAS_ACTIVATION,
                              IntentCategory.BUSINESS_ACCOUNT_RECHARGE,
                              IntentCategory.BUSINESS_PLAN_UNSUBSCRIBE}:
                return await self._prepare_write(message, conv_id, new_intent, context)
            return None

        return BusinessServiceResult(
            f"请明确回复“确认办理”或“取消”。待确认内容：{pending['summary']}",
            pending_intent,
        )

    async def _execute_confirmed(self, confirmed: Dict[str, Any], context: Dict[str, Any]) -> BusinessServiceResult:
        intent = self._pending_intent(confirmed)
        tool_name = confirmed["tool_name"]
        params = dict(confirmed["normalized_params"])
        params["confirmation_id"] = confirmed["confirmation_id"]
        params["idempotency_key"] = hashlib.sha256(
            f"{confirmed['user_id']}:{confirmed['confirmation_id']}:{tool_name}".encode("utf-8")
        ).hexdigest()
        result = await self.tools.call(tool_name, params, context, use_cache=False)
        if not result.success or not isinstance(result.data, dict):
            return BusinessServiceResult(
                "Demo Tool 执行异常，当前为 Demo 人工介入标记，未创建真实工单。",
                intent,
                success=False,
                escalated=True,
            )
        payload = result.data
        if not payload.get("success"):
            return self._business_error(payload, intent)
        return BusinessServiceResult(self._format_write_success(payload), intent)

    @staticmethod
    def _pending_intent(record: Dict[str, Any]) -> IntentCategory:
        raw = record.get("business_intent")
        try:
            return IntentCategory(raw)
        except (TypeError, ValueError):
            return IntentCategory.BUSINESS_TRANSACTION_STATUS

    async def _account_summary(self, intent: IntentCategory, context: Dict[str, Any]) -> BusinessServiceResult:
        result = await self.tools.call("get_account_summary", {}, context, use_cache=False)
        if not result.success or not isinstance(result.data, dict):
            return BusinessServiceResult("Demo 账户查询暂不可用。", intent, success=False)
        payload = result.data
        if not payload.get("success"):
            return self._business_error(payload, intent)
        data = payload["data"]
        plan_name = data["current_plan"]["name"] if data.get("current_plan") else "无当前套餐"
        return BusinessServiceResult(
            "Demo 账户查询结果：\n"
            f"- 移动标识：{data['mobile_alias']}\n"
            f"- 当前套餐：{plan_name}\n"
            f"- 余额：{data['balance_cents'] / 100:.2f}元\n"
            f"- 剩余流量：{data['remaining_data_mb'] / 1024:g}GB\n"
            f"- 剩余通话：{data['remaining_voice_minutes']}分钟",
            intent,
        )

    async def _plan_query(self, message: str, intent: IntentCategory,
                          context: Dict[str, Any]) -> BusinessServiceResult:
        plans = await self._plans(context)
        if not plans:
            return BusinessServiceResult("Demo 套餐查询暂不可用。", intent, success=False)
        target = self._match_plan(message, plans)
        if target:
            return BusinessServiceResult(self._format_plan(target), intent)
        return BusinessServiceResult("当前可选的纯合成 Demo 套餐：\n" +
                                     "\n".join(f"- {self._format_plan(p)}" for p in plans), intent)

    async def _recommend_plan(self, message: str, conv_id: str, intent: IntentCategory,
                              context: Dict[str, Any]) -> BusinessServiceResult:
        budget_match = re.search(r"(?:预算|控制在|不超过)?\s*(\d+)\s*元", message, re.I)
        data_match = re.search(r"(\d+(?:\.\d+)?)\s*g(?:b)?", message, re.I)
        voice_match = re.search(r"(\d+)\s*分钟", message)
        if not any((budget_match, data_match, voice_match)):
            return BusinessServiceResult(
                "为了推荐合适的套餐，请告诉我：每月预算、预计需要多少GB流量，以及大概需要多少通话分钟。",
                intent,
            )
        params: Dict[str, Any] = {}
        if budget_match:
            params["max_monthly_fee_cents"] = int(budget_match.group(1)) * 100
        if data_match:
            params["min_data_mb"] = int(float(data_match.group(1)) * 1024)
        if voice_match:
            params["min_voice_minutes"] = int(voice_match.group(1))
        result = await self.tools.call("list_plans", params, context)
        plans = self._payload_data(result)
        if not plans:
            return BusinessServiceResult("当前没有同时满足这些条件的 Demo 套餐，可以适当调整预算或用量。", intent)
        selected = plans[0]
        await self.confirmations.set_selection(conv_id, {"kind": "plan", "id": selected["plan_id"]})
        return BusinessServiceResult(
            f"建议优先考虑：{self._format_plan(selected)}\n这是纯合成 Demo 方案，不代表真实在售资费。"
            "如果希望办理，请明确说“办理这个套餐”，我会先给出交易确认问题。",
            intent,
        )

    async def _product_query(self, message: str, intent: IntentCategory,
                             context: Dict[str, Any]) -> BusinessServiceResult:
        product_type = None
        if "流量" in message:
            product_type = "data_pack"
        elif "语音" in message or "通话" in message:
            product_type = "voice_pack"
        elif any(word in message for word in ("彩铃", "来电提醒", "增值")):
            product_type = "vas"
        params = {"product_type": product_type} if product_type else {}
        result = await self.tools.call("list_products", params, context)
        products = self._payload_data(result)
        if not products:
            return BusinessServiceResult("当前没有匹配的 Demo 产品。", intent)
        return BusinessServiceResult("当前可选的纯合成 Demo 产品：\n" +
                                     "\n".join(f"- {self._format_product(p)}" for p in products), intent)

    async def _transaction_status(self, intent: IntentCategory,
                                  context: Dict[str, Any]) -> BusinessServiceResult:
        result = await self.tools.call("get_transaction_status", {}, context, use_cache=False)
        if not result.success or not isinstance(result.data, dict):
            return BusinessServiceResult("Demo 交易查询暂不可用。", intent, success=False)
        payload = result.data
        if not payload.get("success"):
            return self._business_error(payload, intent)
        tx = payload["data"]
        return BusinessServiceResult(
            f"最近一笔 Demo 交易状态：{tx['status']}，交易编号：{tx['transaction_id']}。",
            intent,
        )

    async def _prepare_write(self, message: str, conv_id: str, intent: IntentCategory,
                             context: Dict[str, Any]) -> BusinessServiceResult:
        operation_params: Dict[str, Any]
        if intent == IntentCategory.BUSINESS_PLAN_UNSUBSCRIBE:
            operation_params = {"operation": "unsubscribe_plan"}
        elif intent == IntentCategory.BUSINESS_PLAN_CHANGE:
            plans = await self._plans(context)
            plan = self._match_plan(message, plans)
            if plan is None and any(word in message for word in ("这个套餐", "这个方案", "就这个")):
                selection = await self.confirmations.get_selection(conv_id)
                if selection and selection.get("kind") == "plan":
                    plan = next((p for p in plans if p["plan_id"] == selection["id"]), None)
            if plan is None:
                return BusinessServiceResult("请先指定要变更的 Demo 套餐名称、价格或流量档位。", intent)
            operation_params = {"operation": "change_plan", "target_plan_id": plan["plan_id"]}
        elif intent in {IntentCategory.BUSINESS_DATA_PACK_PURCHASE,
                        IntentCategory.BUSINESS_VOICE_PACK_PURCHASE,
                        IntentCategory.BUSINESS_VAS_ACTIVATION}:
            product_type = {
                IntentCategory.BUSINESS_DATA_PACK_PURCHASE: "data_pack",
                IntentCategory.BUSINESS_VOICE_PACK_PURCHASE: "voice_pack",
                IntentCategory.BUSINESS_VAS_ACTIVATION: "vas",
            }[intent]
            products = await self._products(product_type, context)
            product = self._match_product(message, products)
            if product is None:
                return BusinessServiceResult(
                    f"请先指定要购买的具体 Demo {self.BUSINESS_LABELS[product_type]}。\n" +
                    "\n".join(f"- {self._format_product(p)}" for p in products),
                    intent,
                )
            operation_params = {"operation": "purchase_product", "product_id": product["product_id"]}
        else:
            amount_match = re.search(r"(?:充值|充)\s*(\d+(?:\.\d+)?)\s*元", message)
            if not amount_match:
                return BusinessServiceResult("请说明要进行多少元的 Demo 模拟充值。", intent)
            amount_cents = int(round(float(amount_match.group(1)) * 100))
            operation_params = {"operation": "recharge_account", "amount_cents": amount_cents}

        result = await self.tools.call("prepare_business_operation", operation_params, context, use_cache=False)
        if not result.success or not isinstance(result.data, dict):
            return BusinessServiceResult("Demo 办理准备 Tool 暂不可用，未执行任何写操作。", intent, success=False)
        payload = result.data
        if not payload.get("success"):
            return self._business_error(payload, intent)
        return BusinessServiceResult(payload["data"]["confirmation_prompt"], intent)

    async def _plans(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._payload_data(await self.tools.call("list_plans", {}, context)) or []

    async def _products(self, product_type: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._payload_data(await self.tools.call("list_products", {"product_type": product_type}, context)) or []

    @staticmethod
    def _payload_data(tool_result: Any) -> Any:
        if not tool_result.success or not isinstance(tool_result.data, dict) or not tool_result.data.get("success"):
            return None
        return tool_result.data.get("data")

    @staticmethod
    def _match_plan(message: str, plans: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        lowered = message.lower().replace(" ", "")
        for plan in plans:
            if plan["plan_id"].lower() in lowered or plan["name"].lower().replace(" ", "") in lowered:
                return plan
        price = re.search(r"(\d+)元(?:的)?套餐", lowered)
        if price:
            cents = int(price.group(1)) * 100
            return next((p for p in plans if p["monthly_fee_cents"] == cents), None)
        data = re.search(r"(\d+(?:\.\d+)?)g(?:b)?", lowered)
        if data:
            mb = int(float(data.group(1)) * 1024)
            return next((p for p in plans if p["data_mb"] == mb), None)
        return None

    @staticmethod
    def _match_product(message: str, products: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        lowered = message.lower().replace(" ", "")
        for product in products:
            if product["product_id"].lower() in lowered or product["name"].lower().replace(" ", "") in lowered:
                return product
        data = re.search(r"(\d+(?:\.\d+)?)g(?:b)?", lowered)
        if data:
            mb = int(float(data.group(1)) * 1024)
            match = next((p for p in products if p.get("quota_mb") == mb), None)
            if match:
                return match
        voice = re.search(r"(\d+)分钟", lowered)
        if voice:
            match = next((p for p in products if p.get("voice_minutes") == int(voice.group(1))), None)
            if match:
                return match
        keyword_map = {"视频彩铃": "demo_vas_video_ringtone", "彩铃": "demo_vas_video_ringtone",
                       "来电提醒": "demo_vas_missed_call_alert"}
        for keyword, product_id in keyword_map.items():
            if keyword in lowered:
                return next((p for p in products if p["product_id"] == product_id), None)
        return None

    @staticmethod
    def _format_plan(plan: Dict[str, Any]) -> str:
        benefits = f"；附加{'、'.join(plan['directional_benefits'])}" if plan.get("directional_benefits") else ""
        return (f"{plan['name']}：{plan['monthly_fee_cents'] / 100:g}元/月，"
                f"{plan['data_mb'] / 1024:g}GB通用流量，{plan['voice_minutes']}分钟国内主叫{benefits}")

    @staticmethod
    def _format_product(product: Dict[str, Any]) -> str:
        price = product["price_cents"] / 100
        if product["product_type"] == "data_pack":
            return f"{product['name']}：{price:g}元，{product['quota_mb'] / 1024:g}GB，有效期{product['validity_days']}天"
        if product["product_type"] == "voice_pack":
            return f"{product['name']}：{price:g}元，{product['voice_minutes']}分钟，有效期{product['validity_days']}天"
        return f"{product['name']}：{price:g}元/月，立即生效，Demo按月续订关系"

    @staticmethod
    def _format_write_success(payload: Dict[str, Any]) -> str:
        tool_name = payload["tool_name"]
        data = payload["data"]
        tx = payload["transaction_id"]
        if tool_name == "change_plan":
            if data["action"] == "change":
                detail = f"套餐已变更为{data['current_plan']['name']}"
            else:
                detail = "当前套餐已退订，剩余流量和通话已清零"
        elif tool_name == "purchase_product":
            detail = f"{data['product']['name']}已办理"
        else:
            detail = f"已完成{data['amount_cents'] / 100:g}元 Demo 模拟充值"
        return f"Demo 操作成功：{detail}。交易编号：{tx}。"

    @staticmethod
    def _business_error(payload: Dict[str, Any], intent: IntentCategory) -> BusinessServiceResult:
        error = payload.get("error") or {}
        code = error.get("code", "INTERNAL_ERROR")
        message = error.get("message", "Demo 业务处理失败。")
        escalated = code in {"MANUAL_REVIEW_REQUIRED", "TOOL_TIMEOUT", "INTERNAL_ERROR"}
        transaction_id = payload.get("transaction_id")
        if escalated and transaction_id:
            message += f" Demo 参考交易编号：{transaction_id}。"
        if escalated:
            message += " 当前为 Demo 人工介入标记，未创建真实工单。"
        return BusinessServiceResult(message, intent, success=False, escalated=escalated)
