"""BusinessAgent 使用的纯合成 Mock CRM、确认状态和 Tool handlers。"""

import asyncio
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import redis.asyncio as redis_async

from mcp.tool_manager import MCPToolManager, Tool


CONFIRMATION_TTL_SECONDS = 300
TRANSACTION_RETENTION_DAYS = 7


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _stable_hash(value: Dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BusinessAuthContext:
    authenticated: bool
    user_id: Optional[str] = None
    error_code: Optional[str] = None


class ConfirmationStore:
    """Redis 确认状态接口；测试可替换为内存实现。"""

    async def create(self, user_id: str, conv_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    async def get_pending(self, user_id: str, conv_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def get_record(self, user_id: str, confirmation_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def confirm(self, user_id: str, conv_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def cancel(self, user_id: str, conv_id: str) -> None:
        raise NotImplementedError

    async def consume(
        self,
        user_id: str,
        confirmation_id: str,
        tool_name: str,
        normalized_params: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def set_selection(self, conv_id: str, selection: Dict[str, Any]) -> None:
        raise NotImplementedError

    async def get_selection(self, conv_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class RedisConfirmationStore(ConfirmationStore):
    def __init__(self, redis_url: str):
        self._redis = redis_async.from_url(redis_url, decode_responses=True)

    @staticmethod
    def _key(user_id: str, confirmation_id: str) -> str:
        return f"demo_confirm:{user_id}:{confirmation_id}"

    @staticmethod
    def _pending_key(user_id: str, conv_id: str) -> str:
        return f"demo_confirm_pending:{user_id}:{conv_id}"

    @staticmethod
    def _selection_key(conv_id: str) -> str:
        return f"demo_business_selection:{conv_id}"

    async def create(self, user_id: str, conv_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        await self.cancel(user_id, conv_id)
        confirmation_id = f"demo_confirm_{uuid.uuid4().hex}"
        now = _utc_now()
        record = {
            **payload,
            "confirmation_id": confirmation_id,
            "user_id": user_id,
            "conv_id": conv_id,
            "created_at": now,
            "presented_at": now,
            "confirmed_at": None,
            "expires_at": _utc_after(CONFIRMATION_TTL_SECONDS),
            "status": "awaiting_confirmation",
        }
        key = self._key(user_id, confirmation_id)
        pointer = self._pending_key(user_id, conv_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(key, json.dumps(record, ensure_ascii=False), ex=CONFIRMATION_TTL_SECONDS)
            pipe.set(pointer, confirmation_id, ex=CONFIRMATION_TTL_SECONDS)
            await pipe.execute()
        return record

    async def get_pending(self, user_id: str, conv_id: str) -> Optional[Dict[str, Any]]:
        pointer = self._pending_key(user_id, conv_id)
        confirmation_id = await self._redis.get(pointer)
        if not confirmation_id:
            return None
        raw = await self._redis.get(self._key(user_id, confirmation_id))
        if not raw:
            await self._redis.delete(pointer)
            return None
        record = json.loads(raw)
        return record if record.get("status") in {"awaiting_confirmation", "confirmed"} else None

    async def get_record(self, user_id: str, confirmation_id: str) -> Optional[Dict[str, Any]]:
        raw = await self._redis.get(self._key(user_id, confirmation_id))
        return json.loads(raw) if raw else None

    async def confirm(self, user_id: str, conv_id: str) -> Optional[Dict[str, Any]]:
        record = await self.get_pending(user_id, conv_id)
        if not record or record.get("status") != "awaiting_confirmation":
            return None
        record["status"] = "confirmed"
        record["confirmed_at"] = _utc_now()
        key = self._key(user_id, record["confirmation_id"])
        ttl = await self._redis.ttl(key)
        if ttl <= 0:
            return None
        await self._redis.set(key, json.dumps(record, ensure_ascii=False), ex=ttl)
        return record

    async def cancel(self, user_id: str, conv_id: str) -> None:
        pointer = self._pending_key(user_id, conv_id)
        confirmation_id = await self._redis.get(pointer)
        if confirmation_id:
            key = self._key(user_id, confirmation_id)
            raw = await self._redis.get(key)
            if raw:
                record = json.loads(raw)
                record["status"] = "cancelled"
                ttl = await self._redis.ttl(key)
                if ttl > 0:
                    await self._redis.set(key, json.dumps(record, ensure_ascii=False), ex=ttl)
            await self._redis.delete(pointer)

    async def consume(
        self,
        user_id: str,
        confirmation_id: str,
        tool_name: str,
        normalized_params: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        key = self._key(user_id, confirmation_id)
        params_hash = _stable_hash(normalized_params)
        script = """
        local raw = redis.call('GET', KEYS[1])
        if not raw then return nil end
        local record = cjson.decode(raw)
        if record['status'] ~= 'confirmed' or record['tool_name'] ~= ARGV[1]
           or record['params_hash'] ~= ARGV[2] or not record['confirmed_at']
           or not record['presented_at'] or record['confirmed_at'] <= record['presented_at'] then
          return nil
        end
        local ttl = redis.call('TTL', KEYS[1])
        if ttl <= 0 then return nil end
        record['status'] = 'consumed'
        local encoded = cjson.encode(record)
        redis.call('SETEX', KEYS[1], ttl, encoded)
        redis.call('DEL', 'demo_confirm_pending:' .. ARGV[3] .. ':' .. record['conv_id'])
        return encoded
        """
        raw = await self._redis.eval(
            script,
            1,
            key,
            tool_name,
            params_hash,
            user_id,
        )
        if not raw:
            return None
        record = json.loads(raw)
        return record

    async def set_selection(self, conv_id: str, selection: Dict[str, Any]) -> None:
        await self._redis.set(
            self._selection_key(conv_id),
            json.dumps(selection, ensure_ascii=False),
            ex=86400,
        )

    async def get_selection(self, conv_id: str) -> Optional[Dict[str, Any]]:
        raw = await self._redis.get(self._selection_key(conv_id))
        return json.loads(raw) if raw else None


class InMemoryConfirmationStore(ConfirmationStore):
    """标准库测试使用，不用于应用运行时。"""

    def __init__(self):
        self.records: Dict[str, Dict[str, Any]] = {}
        self.pending: Dict[str, str] = {}
        self.selections: Dict[str, Dict[str, Any]] = {}

    async def create(self, user_id: str, conv_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        await self.cancel(user_id, conv_id)
        confirmation_id = f"demo_confirm_{uuid.uuid4().hex}"
        now = _utc_now()
        record = {**payload, "confirmation_id": confirmation_id, "user_id": user_id, "conv_id": conv_id,
                  "created_at": now, "presented_at": now, "confirmed_at": None,
                  "expires_at": _utc_after(CONFIRMATION_TTL_SECONDS),
                  "status": "awaiting_confirmation"}
        self.records[f"{user_id}:{confirmation_id}"] = record
        self.pending[f"{user_id}:{conv_id}"] = confirmation_id
        return dict(record)

    async def get_pending(self, user_id: str, conv_id: str) -> Optional[Dict[str, Any]]:
        confirmation_id = self.pending.get(f"{user_id}:{conv_id}")
        record = self.records.get(f"{user_id}:{confirmation_id}") if confirmation_id else None
        if record and datetime.fromisoformat(record["expires_at"]) <= datetime.now(timezone.utc):
            record["status"] = "expired"
            self.pending.pop(f"{user_id}:{conv_id}", None)
            return None
        return dict(record) if record and record["status"] in {"awaiting_confirmation", "confirmed"} else None

    async def get_record(self, user_id: str, confirmation_id: str) -> Optional[Dict[str, Any]]:
        record = self.records.get(f"{user_id}:{confirmation_id}")
        return dict(record) if record else None

    async def confirm(self, user_id: str, conv_id: str) -> Optional[Dict[str, Any]]:
        pending = await self.get_pending(user_id, conv_id)
        confirmation_id = pending.get("confirmation_id") if pending else None
        record = self.records.get(f"{user_id}:{confirmation_id}") if confirmation_id else None
        if not record or record["status"] != "awaiting_confirmation":
            return None
        record["status"] = "confirmed"
        record["confirmed_at"] = _utc_now()
        return dict(record)

    async def cancel(self, user_id: str, conv_id: str) -> None:
        confirmation_id = self.pending.pop(f"{user_id}:{conv_id}", None)
        if confirmation_id:
            record = self.records.get(f"{user_id}:{confirmation_id}")
            if record:
                record["status"] = "cancelled"

    async def consume(self, user_id: str, confirmation_id: str, tool_name: str,
                      normalized_params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        record = self.records.get(f"{user_id}:{confirmation_id}")
        if not record or record["status"] != "confirmed" or record["tool_name"] != tool_name:
            return None
        if datetime.fromisoformat(record["expires_at"]) <= datetime.now(timezone.utc):
            record["status"] = "expired"
            self.pending.pop(f"{user_id}:{record['conv_id']}", None)
            return None
        if not record.get("confirmed_at") or record["confirmed_at"] <= record["presented_at"]:
            return None
        if record["params_hash"] != _stable_hash(normalized_params):
            return None
        record["status"] = "consumed"
        self.pending.pop(f"{user_id}:{record['conv_id']}", None)
        return dict(record)

    async def set_selection(self, conv_id: str, selection: Dict[str, Any]) -> None:
        self.selections[conv_id] = dict(selection)

    async def get_selection(self, conv_id: str) -> Optional[Dict[str, Any]]:
        selection = self.selections.get(conv_id)
        return dict(selection) if selection else None


class MockCRMBackend:
    def __init__(self, seed_path: str, runtime_path: str, confirmations: ConfirmationStore):
        self.seed_path = Path(seed_path).resolve()
        self.runtime_path = Path(runtime_path).resolve()
        self.confirmations = confirmations
        self._lock = threading.RLock()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        with self._lock:
            if not self.seed_path.exists():
                raise FileNotFoundError(f"Mock CRM 种子文件不存在: {self.seed_path}")
            self.runtime_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.runtime_path.exists():
                shutil.copyfile(self.seed_path, self.runtime_path)
            data = json.loads(self.runtime_path.read_text(encoding="utf-8"))
            if self._prune_expired_transactions(data):
                self._write_sync(data)

    def _read_sync(self) -> Dict[str, Any]:
        with self._lock:
            data = json.loads(self.runtime_path.read_text(encoding="utf-8"))
            if self._prune_expired_transactions(data):
                self._write_sync(data)
            return data

    def _write_sync(self, data: Dict[str, Any]) -> None:
        with self._lock:
            fd, temp_name = tempfile.mkstemp(prefix="mock_crm_", suffix=".json", dir=self.runtime_path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(data, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                os.replace(temp_name, self.runtime_path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)

    @staticmethod
    def _prune_expired_transactions(data: Dict[str, Any]) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=TRANSACTION_RETENTION_DAYS)
        original = list(data.get("transactions", []))
        retained = []
        for transaction in original:
            try:
                created_at = datetime.fromisoformat(str(transaction["created_at"]))
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                if created_at >= cutoff:
                    retained.append(transaction)
            except (KeyError, TypeError, ValueError):
                # 未知时间格式安全保留，避免因损坏数据误删交易。
                retained.append(transaction)
        data["transactions"] = retained
        return len(retained) != len(original)

    async def authenticate(self, token: Optional[str]) -> BusinessAuthContext:
        if not token:
            return BusinessAuthContext(False, error_code="AUTH_REQUIRED")
        data = await asyncio.to_thread(self._read_sync)
        for item in data.get("mock_tokens", []):
            if hmac.compare_digest(str(item.get("token_value", "")), token):
                if item.get("status") != "active":
                    return BusinessAuthContext(False, error_code="INVALID_TOKEN")
                expires_at = item.get("expires_at")
                if expires_at:
                    try:
                        expires = datetime.fromisoformat(str(expires_at))
                        if expires.tzinfo is None:
                            expires = expires.replace(tzinfo=timezone.utc)
                        if expires <= datetime.now(timezone.utc):
                            return BusinessAuthContext(False, error_code="INVALID_TOKEN")
                    except ValueError:
                        return BusinessAuthContext(False, error_code="INVALID_TOKEN")
                return BusinessAuthContext(True, str(item["user_id"]), None)
        return BusinessAuthContext(False, error_code="INVALID_TOKEN")

    @staticmethod
    def _context_user(context: Optional[Dict[str, Any]]) -> Optional[str]:
        if not context or not context.get("authenticated"):
            return None
        return str(context.get("authenticated_user_id") or "") or None

    @staticmethod
    def _ok(tool_name: str, data: Any, transaction_id: Optional[str] = None) -> Dict[str, Any]:
        return {"success": True, "status": "succeeded", "tool_name": tool_name,
                "transaction_id": transaction_id, "data": data, "error": None, "demo": True}

    @staticmethod
    def _fail(tool_name: str, code: str, message: str, status: str = "failed") -> Dict[str, Any]:
        return {"success": False, "status": status, "tool_name": tool_name, "transaction_id": None,
                "data": None, "error": {"code": code, "message": message}, "demo": True}

    @staticmethod
    def _find_user(data: Dict[str, Any], user_id: str) -> Optional[Dict[str, Any]]:
        return next((u for u in data.get("users", []) if u.get("user_id") == user_id), None)

    async def get_account_summary(self, params: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        user_id = self._context_user(context)
        if not user_id:
            return self._fail("get_account_summary", "AUTH_REQUIRED", "需要有效的 Mock Token。")
        data = await asyncio.to_thread(self._read_sync)
        user = self._find_user(data, user_id)
        if not user:
            return self._fail("get_account_summary", "NOT_FOUND", "Demo 账户不存在。")
        plan = next((p for p in data["plans"] if p["plan_id"] == user.get("current_plan_id")), None)
        result = {k: user[k] for k in ("mobile_alias", "account_status", "balance_cents", "currency",
                                        "remaining_data_mb", "remaining_voice_minutes")}
        result["current_plan"] = plan
        return self._ok("get_account_summary", result)

    async def list_plans(self, params: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        data = await asyncio.to_thread(self._read_sync)
        plans = [p for p in data["plans"] if p.get("status") == "active"]
        max_fee = params.get("max_monthly_fee_cents")
        min_data = params.get("min_data_mb")
        min_voice = params.get("min_voice_minutes")
        if max_fee is not None:
            plans = [p for p in plans if p["monthly_fee_cents"] <= max_fee]
        if min_data is not None:
            plans = [p for p in plans if p["data_mb"] >= min_data]
        if min_voice is not None:
            plans = [p for p in plans if p["voice_minutes"] >= min_voice]
        plans.sort(key=lambda p: (p["monthly_fee_cents"], p["plan_id"]))
        return self._ok("list_plans", plans)

    async def list_products(self, params: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        data = await asyncio.to_thread(self._read_sync)
        products = [p for p in data["products"] if p.get("status") == "active"]
        if params.get("product_type"):
            products = [p for p in products if p["product_type"] == params["product_type"]]
        if params.get("max_price_cents") is not None:
            products = [p for p in products if p["price_cents"] <= params["max_price_cents"]]
        products.sort(key=lambda p: (p["price_cents"], p["product_id"]))
        return self._ok("list_products", products)

    async def prepare_business_operation(self, params: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        user_id = self._context_user(context)
        conv_id = str((context or {}).get("conv_id") or "")
        if not user_id:
            return self._fail("prepare_business_operation", "AUTH_REQUIRED", "办理业务需要有效的 Mock Token。")
        if not conv_id:
            return self._fail("prepare_business_operation", "INVALID_ARGUMENT", "缺少会话标识。")
        data = await asyncio.to_thread(self._read_sync)
        user = self._find_user(data, user_id)
        if not user:
            return self._fail("prepare_business_operation", "NOT_FOUND", "Demo 账户不存在。")
        if user.get("account_status") != "active":
            return self._fail("prepare_business_operation", "MANUAL_REVIEW_REQUIRED", "账户状态异常，需要人工处理。", "manual_review")

        operation = str(params.get("operation") or "")
        tool_name = ""
        normalized: Dict[str, Any]
        prompt = ""
        summary = ""

        if operation == "change_plan":
            plan_id = str(params.get("target_plan_id") or "")
            plan = next((p for p in data["plans"] if p["plan_id"] == plan_id and p["status"] == "active"), None)
            if not plan:
                return self._fail("prepare_business_operation", "NOT_FOUND", "目标 Demo 套餐不存在。")
            if user["balance_cents"] < plan["monthly_fee_cents"]:
                return self._fail("prepare_business_operation", "INSUFFICIENT_BALANCE", "Demo 账户余额不足。")
            tool_name = "change_plan"
            business_intent = "business_plan_change"
            normalized = {"action": "change", "target_plan_id": plan_id,
                          "quoted_price_cents": plan["monthly_fee_cents"]}
            price = plan["monthly_fee_cents"] / 100
            prompt = (f"您确认变更为{plan['name']}，价格{price:g}元，将立即生效并扣除全额月费，"
                      "原套餐费用不退，剩余流量和通话将按新套餐重置且原附加资源不结转，确认办理吗？")
            summary = prompt.rstrip("？")
        elif operation == "unsubscribe_plan":
            if not user.get("current_plan_id"):
                return self._fail("prepare_business_operation", "INVALID_STATE", "当前没有可退订的套餐。")
            tool_name = "change_plan"
            business_intent = "business_plan_unsubscribe"
            normalized = {"action": "unsubscribe", "quoted_price_cents": 0}
            prompt = "您确认退订当前套餐吗？退订立即生效，当前套餐将置空、剩余流量和通话将清零且不退款。"
            summary = prompt
        elif operation == "purchase_product":
            product_id = str(params.get("product_id") or "")
            product = next((p for p in data["products"] if p["product_id"] == product_id and p["status"] == "active"), None)
            if not product:
                return self._fail("prepare_business_operation", "NOT_FOUND", "目标 Demo 产品不存在。")
            if user["balance_cents"] < product["price_cents"]:
                return self._fail("prepare_business_operation", "INSUFFICIENT_BALANCE", "Demo 账户余额不足。")
            if product["product_type"] == "vas" and any(
                s["user_id"] == user_id and s["product_id"] == product_id and s["status"] == "active"
                for s in data.get("subscriptions", [])
            ):
                return self._fail("prepare_business_operation", "INVALID_STATE", "该 Demo 增值业务已开通。")
            tool_name = "purchase_product"
            business_intent = {
                "data_pack": "business_data_pack_purchase",
                "voice_pack": "business_voice_pack_purchase",
                "vas": "business_vas_activation",
            }[product["product_type"]]
            normalized = {"product_id": product_id, "quoted_price_cents": product["price_cents"]}
            price = product["price_cents"] / 100
            if product["product_type"] == "data_pack":
                quota = product["quota_mb"] / 1024
                prompt = f"您确认购买{product['name']}，包含{quota:g}GB，价格{price:g}元吗？"
            elif product["product_type"] == "voice_pack":
                prompt = f"您确认购买{product['name']}，包含{product['voice_minutes']}分钟，价格{price:g}元吗？"
            else:
                prompt = f"您确认开通{product['name']}，价格{price:g}元/月，立即生效并建立Demo按月续订关系吗？"
            summary = prompt.rstrip("？")
        elif operation == "recharge_account":
            amount = params.get("amount_cents")
            if not isinstance(amount, int) or amount <= 0:
                return self._fail("prepare_business_operation", "INVALID_ARGUMENT", "充值金额必须大于0。")
            tool_name = "recharge_account"
            business_intent = "business_account_recharge"
            normalized = {"amount_cents": amount, "quoted_price_cents": amount}
            prompt = f"您确认进行{amount / 100:g}元 Demo 模拟充值吗？该操作不连接真实支付系统。"
            summary = prompt
        else:
            return self._fail("prepare_business_operation", "INVALID_ARGUMENT", "不支持的业务操作。")

        record = await self.confirmations.create(user_id, conv_id, {
            "tool_name": tool_name,
            "business_intent": business_intent,
            "normalized_params": normalized,
            "params_hash": _stable_hash(normalized),
            "summary": summary,
            "confirmation_prompt": prompt,
        })
        return self._ok("prepare_business_operation", {
            "confirmation_id": record["confirmation_id"],
            "summary": summary,
            "confirmation_prompt": prompt,
            "expires_at": record["expires_at"],
            "normalized_params": normalized,
            "expires_in_seconds": CONFIRMATION_TTL_SECONDS,
        })

    async def _idempotent_result(self, user_id: str, tool_name: str, key: str,
                                 normalized: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        data = await asyncio.to_thread(self._read_sync)
        expected_hash = _stable_hash(normalized)
        existing = next((t for t in data.get("transactions", [])
                         if t["user_id"] == user_id and t["tool_name"] == tool_name
                         and t["idempotency_key"] == key), None)
        if not existing:
            return None
        if existing["request_payload_hash"] != expected_hash:
            return self._fail(tool_name, "IDEMPOTENCY_CONFLICT", "同一幂等键对应不同参数。")
        return existing.get("result_snapshot")

    async def _authorize_write(self, tool_name: str, params: Dict[str, Any], context: Optional[Dict[str, Any]],
                               normalized: Dict[str, Any]) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
        user_id = self._context_user(context)
        if not user_id:
            return None, self._fail(tool_name, "AUTH_REQUIRED", "写操作需要有效的 Mock Token。")
        key = str(params.get("idempotency_key") or "")
        if not key:
            return None, self._fail(tool_name, "INVALID_ARGUMENT", "缺少幂等键。")
        replay = await self._idempotent_result(user_id, tool_name, key, normalized)
        if replay is not None:
            return None, replay
        confirmation_id = str(params.get("confirmation_id") or "")
        confirmed = await self.confirmations.consume(user_id, confirmation_id, tool_name, normalized)
        if not confirmed:
            return None, self._fail(tool_name, "CONFIRMATION_NOT_CONFIRMED", "缺少有效的下一轮用户确认。")
        return user_id, None

    @staticmethod
    def _write_details(tool_name: str, params: Dict[str, Any]) -> tuple[Dict[str, Any], str, int]:
        if tool_name == "change_plan":
            normalized = {
                "action": params.get("action"),
                "quoted_price_cents": params.get("quoted_price_cents"),
            }
            if params.get("action") == "change":
                normalized["target_plan_id"] = params.get("target_plan_id")
            return normalized, str(params.get("action") or ""), int(params.get("quoted_price_cents") or 0)
        if tool_name == "purchase_product":
            normalized = {
                "product_id": params.get("product_id"),
                "quoted_price_cents": params.get("quoted_price_cents"),
            }
            return normalized, "purchase", int(params.get("quoted_price_cents") or 0)
        normalized = {
            "amount_cents": params.get("amount_cents"),
            "quoted_price_cents": params.get("quoted_price_cents"),
        }
        return normalized, "DEMO_RECHARGE", int(params.get("amount_cents") or 0)

    async def write_tool_fallback(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        error: str,
    ) -> Dict[str, Any]:
        """Resolve a failed write by idempotency, or persist a non-retryable uncertain state."""
        user_id = self._context_user(context)
        idempotency_key = str(params.get("idempotency_key") or "")
        confirmation_id = str(params.get("confirmation_id") or "")
        if not user_id:
            return self._fail(tool_name, "AUTH_REQUIRED", "写操作需要有效的 Mock Token。")
        if not idempotency_key or not confirmation_id:
            return self._fail(tool_name, "INVALID_ARGUMENT", "缺少确认标识或幂等键。")

        normalized, operation, amount = self._write_details(tool_name, params)
        replay = await self._idempotent_result(user_id, tool_name, idempotency_key, normalized)
        if replay is not None:
            return replay

        confirmation = await self.confirmations.get_record(user_id, confirmation_id)
        if not confirmation or confirmation.get("tool_name") != tool_name \
                or confirmation.get("params_hash") != _stable_hash(normalized):
            return self._fail(tool_name, "CONFIRMATION_NOT_CONFIRMED", "缺少有效的下一轮用户确认。")
        if confirmation.get("status") == "confirmed":
            consumed = await self.confirmations.consume(user_id, confirmation_id, tool_name, normalized)
            if not consumed:
                return self._fail(tool_name, "CONFIRMATION_NOT_CONFIRMED", "确认上下文已失效。")
        elif confirmation.get("status") != "consumed":
            return self._fail(tool_name, "CONFIRMATION_NOT_CONFIRMED", "确认上下文不可执行。")

        timed_out = "超时" in error
        status = "unknown" if timed_out else "manual_review"
        error_code = "TOOL_TIMEOUT" if timed_out else "INTERNAL_ERROR"
        message = (
            "Demo Tool 执行超时，结果未知，不能自动重试。"
            if timed_out else
            "Demo Tool 执行异常，结果需要人工核验。"
        )
        return await asyncio.to_thread(
            self._record_write_fallback_sync,
            user_id,
            tool_name,
            operation,
            idempotency_key,
            normalized,
            amount,
            status,
            error_code,
            message,
        )

    def _record_write_fallback_sync(
        self,
        user_id: str,
        tool_name: str,
        operation: str,
        idempotency_key: str,
        normalized: Dict[str, Any],
        amount: int,
        status: str,
        error_code: str,
        message: str,
    ) -> Dict[str, Any]:
        with self._lock:
            data = self._read_sync()
            request_hash = _stable_hash(normalized)
            existing = next((t for t in data.get("transactions", [])
                             if t["user_id"] == user_id and t["tool_name"] == tool_name
                             and t["idempotency_key"] == idempotency_key), None)
            if existing:
                if existing["request_payload_hash"] != request_hash:
                    return self._fail(tool_name, "IDEMPOTENCY_CONFLICT", "同一幂等键对应不同参数。")
                return existing["result_snapshot"]

            transaction_id = f"demo_tx_{uuid.uuid4().hex}"
            response = {
                "success": False,
                "status": status,
                "tool_name": tool_name,
                "transaction_id": transaction_id,
                "data": None,
                "error": {"code": error_code, "message": message},
                "demo": True,
            }
            now = _utc_now()
            data["transactions"].append({
                "transaction_id": transaction_id,
                "user_id": user_id,
                "tool_name": tool_name,
                "operation": operation,
                "idempotency_key": idempotency_key,
                "status": status,
                "amount_cents": max(0, amount),
                "request_payload_hash": request_hash,
                "result_snapshot": response,
                "error_code": error_code,
                "created_at": now,
                "completed_at": None,
            })
            self._write_sync(data)
            return response

    def _commit_transaction_sync(self, user_id: str, tool_name: str, operation: str,
                                 idempotency_key: str, normalized: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self._read_sync()
            self._prune_expired_transactions(data)
            request_hash = _stable_hash(normalized)
            existing = next((t for t in data.get("transactions", [])
                             if t["user_id"] == user_id and t["tool_name"] == tool_name
                             and t["idempotency_key"] == idempotency_key), None)
            if existing:
                if existing["request_payload_hash"] != request_hash:
                    return self._fail(tool_name, "IDEMPOTENCY_CONFLICT", "同一幂等键对应不同参数。")
                return existing["result_snapshot"]
            user = self._find_user(data, user_id)
            if not user:
                return self._fail(tool_name, "NOT_FOUND", "Demo 账户不存在。")
            if user.get("account_status") != "active":
                return self._fail(tool_name, "MANUAL_REVIEW_REQUIRED", "账户状态异常，需要人工处理。", "manual_review")

            amount = 0
            result_data: Dict[str, Any] = {}
            if tool_name == "change_plan":
                if normalized["action"] == "change":
                    plan = next((p for p in data["plans"] if p["plan_id"] == normalized["target_plan_id"]
                                 and p["status"] == "active"), None)
                    if not plan or plan["monthly_fee_cents"] != normalized["quoted_price_cents"]:
                        return self._fail(tool_name, "CONFIRMATION_MISMATCH", "套餐或价格已变化，请重新确认。")
                    amount = plan["monthly_fee_cents"]
                    if user["balance_cents"] < amount:
                        return self._fail(tool_name, "INSUFFICIENT_BALANCE", "Demo 账户余额不足。")
                    user["balance_cents"] -= amount
                    user["current_plan_id"] = plan["plan_id"]
                    user["remaining_data_mb"] = plan["data_mb"]
                    user["remaining_voice_minutes"] = plan["voice_minutes"]
                    result_data = {"action": "change", "current_plan": plan, "balance_cents": user["balance_cents"],
                                   "remaining_data_mb": user["remaining_data_mb"],
                                   "remaining_voice_minutes": user["remaining_voice_minutes"]}
                else:
                    user["current_plan_id"] = None
                    user["remaining_data_mb"] = 0
                    user["remaining_voice_minutes"] = 0
                    result_data = {"action": "unsubscribe", "current_plan": None, "balance_cents": user["balance_cents"],
                                   "remaining_data_mb": 0, "remaining_voice_minutes": 0}
            elif tool_name == "purchase_product":
                product = next((p for p in data["products"] if p["product_id"] == normalized["product_id"]
                                and p["status"] == "active"), None)
                if not product or product["price_cents"] != normalized["quoted_price_cents"]:
                    return self._fail(tool_name, "CONFIRMATION_MISMATCH", "产品或价格已变化，请重新确认。")
                amount = product["price_cents"]
                if user["balance_cents"] < amount:
                    return self._fail(tool_name, "INSUFFICIENT_BALANCE", "Demo 账户余额不足。")
                if product["product_type"] == "vas" and any(
                    s["user_id"] == user_id and s["product_id"] == product["product_id"] and s["status"] == "active"
                    for s in data.get("subscriptions", [])
                ):
                    return self._fail(tool_name, "INVALID_STATE", "该 Demo 增值业务已开通。")
                user["balance_cents"] -= amount
                if product["product_type"] == "data_pack":
                    user["remaining_data_mb"] += product["quota_mb"]
                elif product["product_type"] == "voice_pack":
                    user["remaining_voice_minutes"] += product["voice_minutes"]
                else:
                    data["subscriptions"].append({
                        "subscription_id": f"demo_sub_{uuid.uuid4().hex}", "user_id": user_id,
                        "product_id": product["product_id"], "status": "active", "started_at": _utc_now(),
                        "expires_at": None, "transaction_id": "PENDING",
                    })
                result_data = {"product": product, "balance_cents": user["balance_cents"],
                               "remaining_data_mb": user["remaining_data_mb"],
                               "remaining_voice_minutes": user["remaining_voice_minutes"]}
            else:
                amount = normalized["amount_cents"]
                user["balance_cents"] += amount
                result_data = {"amount_cents": amount, "balance_cents": user["balance_cents"], "demo_recharge": True}

            user["version"] += 1
            transaction_id = f"demo_tx_{uuid.uuid4().hex}"
            if tool_name == "purchase_product" and data["subscriptions"] and data["subscriptions"][-1]["transaction_id"] == "PENDING":
                data["subscriptions"][-1]["transaction_id"] = transaction_id
            response = self._ok(tool_name, result_data, transaction_id)
            now = _utc_now()
            data["transactions"].append({
                "transaction_id": transaction_id, "user_id": user_id, "tool_name": tool_name,
                "operation": operation, "idempotency_key": idempotency_key, "status": "succeeded",
                "amount_cents": amount, "request_payload_hash": request_hash,
                "result_snapshot": response, "error_code": None, "created_at": now, "completed_at": now,
            })
            self._write_sync(data)
            return response

    async def change_plan(self, params: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        normalized = {"action": params.get("action"), "quoted_price_cents": params.get("quoted_price_cents")}
        if params.get("action") == "change":
            normalized["target_plan_id"] = params.get("target_plan_id")
        user_id, error = await self._authorize_write("change_plan", params, context, normalized)
        if error:
            return error
        return await asyncio.to_thread(self._commit_transaction_sync, user_id, "change_plan",
                                       str(normalized["action"]), str(params["idempotency_key"]), normalized)

    async def purchase_product(self, params: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        normalized = {"product_id": params.get("product_id"), "quoted_price_cents": params.get("quoted_price_cents")}
        user_id, error = await self._authorize_write("purchase_product", params, context, normalized)
        if error:
            return error
        return await asyncio.to_thread(self._commit_transaction_sync, user_id, "purchase_product", "purchase",
                                       str(params["idempotency_key"]), normalized)

    async def recharge_account(self, params: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        normalized = {"amount_cents": params.get("amount_cents"), "quoted_price_cents": params.get("quoted_price_cents")}
        user_id, error = await self._authorize_write("recharge_account", params, context, normalized)
        if error:
            return error
        return await asyncio.to_thread(self._commit_transaction_sync, user_id, "recharge_account", "DEMO_RECHARGE",
                                       str(params["idempotency_key"]), normalized)

    async def get_transaction_status(self, params: Dict[str, Any], context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        user_id = self._context_user(context)
        if not user_id:
            return self._fail("get_transaction_status", "AUTH_REQUIRED", "需要有效的 Mock Token。")
        data = await asyncio.to_thread(self._read_sync)
        transaction_id = params.get("transaction_id")
        tx = next((t for t in reversed(data.get("transactions", []))
                   if t["user_id"] == user_id and (not transaction_id or t["transaction_id"] == transaction_id)), None)
        if not tx:
            return self._fail("get_transaction_status", "NOT_FOUND", "未找到当前 Demo 用户的交易。")
        return self._ok("get_transaction_status", tx, tx["transaction_id"])


def register_mock_crm_tools(manager: MCPToolManager, backend: MockCRMBackend) -> None:
    object_schema = lambda properties, required=None: {
        "type": "object", "properties": properties, "required": required or []
    }
    write_fallback = lambda tool_name: (
        lambda params, context, error: backend.write_tool_fallback(tool_name, params, context, error)
    )
    manager.register(Tool("get_account_summary", "查询当前Demo账户摘要", backend.get_account_summary,
                          object_schema({}), timeout_s=3.0))
    manager.register(Tool("list_plans", "查询可用Demo套餐", backend.list_plans, object_schema({
        "max_monthly_fee_cents": {"type": "integer"}, "min_data_mb": {"type": "integer"},
        "min_voice_minutes": {"type": "integer"},
    }), cache_ttl=60.0, timeout_s=3.0))
    manager.register(Tool("list_products", "查询可用Demo产品", backend.list_products, object_schema({
        "product_type": {"type": "string"}, "max_price_cents": {"type": "integer"},
    }), cache_ttl=60.0, timeout_s=3.0))
    manager.register(Tool("prepare_business_operation", "准备业务并生成两轮确认上下文",
                          backend.prepare_business_operation, object_schema({
                              "operation": {"type": "string"}, "target_plan_id": {"type": "string"},
                              "product_id": {"type": "string"}, "amount_cents": {"type": "integer"},
                          }, ["operation"]), timeout_s=3.0))
    manager.register(Tool("change_plan", "变更或退订Demo套餐", backend.change_plan, object_schema({
        "action": {"type": "string"}, "target_plan_id": {"type": "string"},
        "quoted_price_cents": {"type": "integer"}, "confirmation_id": {"type": "string"},
        "idempotency_key": {"type": "string"},
    }, ["action", "quoted_price_cents", "confirmation_id", "idempotency_key"]), timeout_s=3.0,
                          fallback=write_fallback("change_plan")))
    manager.register(Tool("purchase_product", "购买Demo流量包、语音包或增值业务",
                          backend.purchase_product, object_schema({
                              "product_id": {"type": "string"}, "quoted_price_cents": {"type": "integer"},
                              "confirmation_id": {"type": "string"}, "idempotency_key": {"type": "string"},
                          }, ["product_id", "quoted_price_cents", "confirmation_id", "idempotency_key"]), timeout_s=3.0,
                          fallback=write_fallback("purchase_product")))
    manager.register(Tool("recharge_account", "执行Demo模拟充值", backend.recharge_account, object_schema({
        "amount_cents": {"type": "integer"}, "quoted_price_cents": {"type": "integer"},
        "confirmation_id": {"type": "string"}, "idempotency_key": {"type": "string"},
    }, ["amount_cents", "quoted_price_cents", "confirmation_id", "idempotency_key"]), timeout_s=3.0,
                          fallback=write_fallback("recharge_account")))
    manager.register(Tool("get_transaction_status", "查询当前Demo用户的交易状态",
                          backend.get_transaction_status, object_schema({"transaction_id": {"type": "string"}}),
                          timeout_s=3.0))
