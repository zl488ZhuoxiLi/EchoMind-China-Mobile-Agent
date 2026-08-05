import asyncio
import hashlib
import json
import os
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from core.business_service import BusinessService
from core.intent_recognizer import IntentCategory
from mcp.mock_crm import (
    InMemoryConfirmationStore,
    MockCRMBackend,
    RedisConfirmationStore,
    register_mock_crm_tools,
)
from mcp.tool_manager import MCPToolManager


class BusinessFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.seed = Path("data/demo_crm/mock_crm.json").resolve()
        self.seed_data = json.loads(self.seed.read_text(encoding="utf-8"))
        self.active_tokens = {
            item["user_id"]: item["token_value"]
            for item in self.seed_data["mock_tokens"]
            if item["status"] == "active"
        }
        self.revoked_token = next(
            item["token_value"] for item in self.seed_data["mock_tokens"] if item["status"] == "revoked"
        )
        self.runtime = Path(self.temp_dir.name) / "runtime.json"
        self.confirmations = InMemoryConfirmationStore()
        self.backend = MockCRMBackend(str(self.seed), str(self.runtime), self.confirmations)
        await self.backend.initialize()
        self.tools = MCPToolManager(api_key="test-api-key")
        register_mock_crm_tools(self.tools, self.backend)
        self.service = BusinessService(self.tools, self.backend, self.confirmations)
        self.auth = await self.backend.authenticate(self.active_tokens["demo_user_001"])

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def request(self, message, intent=None, auth=None, conv_id="test_conv_001"):
        return SimpleNamespace(
            message=message,
            intent=intent,
            auth_context=self.auth if auth is None else auth,
            conv_id=conv_id,
            request_id="test_req_001",
        )

    def runtime_data(self):
        return json.loads(self.runtime.read_text(encoding="utf-8"))

    def user(self, user_id="demo_user_001"):
        return next(item for item in self.runtime_data()["users"] if item["user_id"] == user_id)

    async def test_first_purchase_request_only_prepares_then_second_turn_executes(self):
        before = self.user()
        result = await self.service.handle(self.request(
            "确认购买30GB流量包",
            IntentCategory.BUSINESS_DATA_PACK_PURCHASE,
        ))
        self.assertIn("您确认购买Demo 30GB流量包", result.content)
        self.assertEqual(self.user()["balance_cents"], before["balance_cents"])
        self.assertEqual(self.user()["remaining_data_mb"], before["remaining_data_mb"])
        self.assertEqual(len(self.runtime_data()["transactions"]), 0)

        confirmed = await self.service.handle(self.request("确认购买"))
        self.assertIn("Demo 操作成功", confirmed.content)
        self.assertEqual(confirmed.intent, IntentCategory.BUSINESS_DATA_PACK_PURCHASE)
        self.assertEqual(self.user()["balance_cents"], before["balance_cents"] - 5000)
        self.assertEqual(self.user()["remaining_data_mb"], before["remaining_data_mb"] + 30720)
        self.assertEqual(len(self.runtime_data()["transactions"]), 1)

    async def test_reject_confirmation_does_not_write(self):
        before = self.user()
        await self.service.handle(self.request(
            "购买100分钟语音包",
            IntentCategory.BUSINESS_VOICE_PACK_PURCHASE,
        ))
        result = await self.service.handle(self.request("取消"))
        self.assertIn("已取消", result.content)
        self.assertEqual(result.intent, IntentCategory.BUSINESS_VOICE_PACK_PURCHASE)
        self.assertEqual(self.user()["balance_cents"], before["balance_cents"])
        self.assertEqual(len(self.runtime_data()["transactions"]), 0)

    async def test_expired_confirmation_does_not_write(self):
        conv_id = "test_conv_expired"
        await self.service.handle(self.request(
            "购买100分钟语音包",
            IntentCategory.BUSINESS_VOICE_PACK_PURCHASE,
            conv_id=conv_id,
        ))
        pending_id = self.confirmations.pending[f"demo_user_001:{conv_id}"]
        record = self.confirmations.records[f"demo_user_001:{pending_id}"]
        record["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()

        result = await self.service.handle(self.request("确认购买", conv_id=conv_id))
        self.assertIn("没有可执行的待确认", result.content)
        self.assertEqual(len(self.runtime_data()["transactions"]), 0)

    async def test_precise_account_values_use_deterministic_response(self):
        result = await self.service.handle(self.request(
            "我的账户情况",
            IntentCategory.BUSINESS_ACCOUNT_QUERY,
        ))
        self.assertIn("余额：200.00元", result.content)
        self.assertIn("剩余流量：8GB", result.content)
        self.assertIn("剩余通话：90分钟", result.content)

    async def test_insufficient_balance_stops_before_confirmation(self):
        low_auth = await self.backend.authenticate(self.active_tokens["demo_user_002"])
        result = await self.service.handle(self.request(
            "购买30GB流量包",
            IntentCategory.BUSINESS_DATA_PACK_PURCHASE,
            auth=low_auth,
            conv_id="test_conv_low_balance",
        ))
        self.assertFalse(result.success)
        self.assertIn("余额不足", result.content)
        self.assertEqual(len(self.runtime_data()["transactions"]), 0)

    async def test_abnormal_account_escalates(self):
        abnormal_auth = await self.backend.authenticate(self.active_tokens["demo_user_003"])
        result = await self.service.handle(self.request(
            "购买100分钟语音包",
            IntentCategory.BUSINESS_VOICE_PACK_PURCHASE,
            auth=abnormal_auth,
            conv_id="test_conv_abnormal",
        ))
        self.assertTrue(result.escalated)
        self.assertIn("人工介入", result.content)

    async def test_public_catalog_does_not_require_authentication(self):
        anonymous = await self.backend.authenticate(None)
        result = await self.service.handle(self.request(
            "有哪些套餐",
            IntentCategory.BUSINESS_PLAN_QUERY,
            auth=anonymous,
            conv_id="test_conv_public",
        ))
        self.assertTrue(result.success)
        self.assertIn("Demo 轻享套餐", result.content)

    async def test_write_requires_authentication(self):
        anonymous = await self.backend.authenticate(None)
        result = await self.service.handle(self.request(
            "购买30GB流量包",
            IntentCategory.BUSINESS_DATA_PACK_PURCHASE,
            auth=anonymous,
            conv_id="test_conv_no_auth",
        ))
        self.assertFalse(result.success)
        self.assertIn("Mock Token", result.content)

    async def test_plan_change_resets_resources_after_second_turn(self):
        before = self.user()
        first = await self.service.handle(self.request(
            "帮我换成79元套餐",
            IntentCategory.BUSINESS_PLAN_CHANGE,
            conv_id="test_conv_plan_change",
        ))
        self.assertIn("原附加资源不结转", first.content)
        self.assertEqual(self.user()["current_plan_id"], before["current_plan_id"])

        second = await self.service.handle(self.request("确认办理", conv_id="test_conv_plan_change"))
        self.assertTrue(second.success)
        changed = self.user()
        self.assertEqual(changed["current_plan_id"], "demo_plan_plus_79")
        self.assertEqual(changed["remaining_data_mb"], 30720)
        self.assertEqual(changed["remaining_voice_minutes"], 300)
        self.assertEqual(changed["balance_cents"], before["balance_cents"] - 7900)

    async def test_plan_unsubscribe_clears_plan_and_resources_after_confirmation(self):
        before_balance = self.user()["balance_cents"]
        first = await self.service.handle(self.request(
            "我要退订当前套餐",
            IntentCategory.BUSINESS_PLAN_UNSUBSCRIBE,
            conv_id="test_conv_plan_unsubscribe",
        ))
        self.assertIn("清零且不退款", first.content)
        self.assertIsNotNone(self.user()["current_plan_id"])

        second = await self.service.handle(self.request("确认办理", conv_id="test_conv_plan_unsubscribe"))
        self.assertEqual(second.intent, IntentCategory.BUSINESS_PLAN_UNSUBSCRIBE)
        self.assertIsNone(self.user()["current_plan_id"])
        self.assertEqual(self.user()["remaining_data_mb"], 0)
        self.assertEqual(self.user()["remaining_voice_minutes"], 0)
        self.assertEqual(self.user()["balance_cents"], before_balance)

    async def test_vas_activation_creates_one_subscription_after_confirmation(self):
        before_balance = self.user()["balance_cents"]
        first = await self.service.handle(self.request(
            "开通视频彩铃",
            IntentCategory.BUSINESS_VAS_ACTIVATION,
            conv_id="test_conv_vas",
        ))
        self.assertIn("5元/月", first.content)
        self.assertEqual(len(self.runtime_data()["subscriptions"]), 0)

        second = await self.service.handle(self.request("确认开通", conv_id="test_conv_vas"))
        self.assertEqual(second.intent, IntentCategory.BUSINESS_VAS_ACTIVATION)
        self.assertEqual(len(self.runtime_data()["subscriptions"]), 1)
        self.assertEqual(self.user()["balance_cents"], before_balance - 500)

        duplicate = await self.service.handle(self.request(
            "开通视频彩铃",
            IntentCategory.BUSINESS_VAS_ACTIVATION,
            conv_id="test_conv_vas_duplicate",
        ))
        self.assertFalse(duplicate.success)
        self.assertIn("已开通", duplicate.content)
        self.assertEqual(len(self.runtime_data()["subscriptions"]), 1)

    async def test_demo_recharge_requires_second_turn(self):
        before = self.user()["balance_cents"]
        first = await self.service.handle(self.request(
            "给Demo账户充值100元",
            IntentCategory.BUSINESS_ACCOUNT_RECHARGE,
            conv_id="test_conv_recharge",
        ))
        self.assertIn("不连接真实支付系统", first.content)
        self.assertEqual(self.user()["balance_cents"], before)
        second = await self.service.handle(self.request("确认办理", conv_id="test_conv_recharge"))
        self.assertIn("Demo 模拟充值", second.content)
        self.assertEqual(self.user()["balance_cents"], before + 10000)

    async def test_manual_service_does_not_call_write_tool(self):
        result = await self.service.handle(self.request(
            "我要注销号码",
            IntentCategory.BUSINESS_MANUAL_SERVICE,
            conv_id="test_conv_manual",
        ))
        self.assertTrue(result.escalated)
        self.assertEqual(len(self.runtime_data()["transactions"]), 0)

    async def test_idempotent_replay_returns_original_result_once(self):
        context = {
            "authenticated": True,
            "authenticated_user_id": "demo_user_001",
            "conv_id": "test_conv_idempotent",
            "request_id": "test_req_idempotent",
            "demo": True,
        }
        prepared = await self.tools.call(
            "prepare_business_operation",
            {"operation": "purchase_product", "product_id": "demo_voice_pack_100min_30d"},
            context,
            use_cache=False,
        )
        confirmation = prepared.data["data"]
        await self.confirmations.confirm("demo_user_001", "test_conv_idempotent")
        params = {
            **confirmation["normalized_params"],
            "confirmation_id": confirmation["confirmation_id"],
            "idempotency_key": "test_idempotency_key",
        }
        first = await self.tools.call("purchase_product", params, context, use_cache=False)
        second = await self.tools.call("purchase_product", params, context, use_cache=False)
        self.assertTrue(first.data["success"])
        self.assertEqual(second.data["transaction_id"], first.data["transaction_id"])
        self.assertEqual(len(self.runtime_data()["transactions"]), 1)

    async def test_changed_price_cannot_reuse_confirmation(self):
        context = {
            "authenticated": True,
            "authenticated_user_id": "demo_user_001",
            "conv_id": "test_conv_price_binding",
            "request_id": "test_req_price_binding",
            "demo": True,
        }
        prepared = await self.tools.call(
            "prepare_business_operation",
            {"operation": "purchase_product", "product_id": "demo_voice_pack_100min_30d"},
            context,
            use_cache=False,
        )
        confirmation = prepared.data["data"]
        await self.confirmations.confirm("demo_user_001", "test_conv_price_binding")
        params = {
            **confirmation["normalized_params"],
            "quoted_price_cents": 1,
            "confirmation_id": confirmation["confirmation_id"],
            "idempotency_key": "test_price_binding_key",
        }
        result = await self.tools.call("purchase_product", params, context, use_cache=False)
        self.assertFalse(result.data["success"])
        self.assertEqual(result.data["error"]["code"], "CONFIRMATION_NOT_CONFIRMED")
        self.assertEqual(len(self.runtime_data()["transactions"]), 0)

    async def test_write_timeout_records_unknown_and_cannot_retry(self):
        conv_id = "test_conv_timeout"
        before = self.user()
        await self.service.handle(self.request(
            "购买100分钟语音包",
            IntentCategory.BUSINESS_VOICE_PACK_PURCHASE,
            conv_id=conv_id,
        ))
        pending = await self.confirmations.get_pending("demo_user_001", conv_id)
        params = {
            **pending["normalized_params"],
            "confirmation_id": pending["confirmation_id"],
            "idempotency_key": hashlib.sha256(
                f"demo_user_001:{pending['confirmation_id']}:purchase_product".encode("utf-8")
            ).hexdigest(),
        }

        tool = self.tools._tools["purchase_product"]
        original_timeout = tool.timeout_s
        original_commit = self.backend._commit_transaction_sync

        def slow_commit(*args):
            time.sleep(0.15)
            return original_commit(*args)

        self.backend._commit_transaction_sync = slow_commit
        tool.timeout_s = 0.01
        try:
            result = await self.service.handle(self.request("确认购买", conv_id=conv_id))
            self.assertFalse(result.success)
            self.assertTrue(result.escalated)
            self.assertIn("结果未知", result.content)
            self.assertIn("Demo 参考交易编号", result.content)
            await asyncio.sleep(0.2)

            transactions = self.runtime_data()["transactions"]
            self.assertEqual(len(transactions), 1)
            self.assertEqual(transactions[0]["status"], "unknown")
            self.assertEqual(transactions[0]["error_code"], "TOOL_TIMEOUT")
            self.assertEqual(self.user()["balance_cents"], before["balance_cents"])
            self.assertEqual(self.user()["remaining_voice_minutes"], before["remaining_voice_minutes"])

            replay = await self.tools.call("purchase_product", params, {
                "authenticated": True,
                "authenticated_user_id": "demo_user_001",
                "conv_id": conv_id,
                "request_id": "test_req_timeout_replay",
                "demo": True,
            }, use_cache=False)
            self.assertFalse(replay.data["success"])
            self.assertEqual(replay.data["status"], "unknown")
            self.assertEqual(replay.data["transaction_id"], transactions[0]["transaction_id"])
            self.assertEqual(len(self.runtime_data()["transactions"]), 1)

            status = await self.service.handle(self.request(
                "刚才的Demo交易状态",
                IntentCategory.BUSINESS_TRANSACTION_STATUS,
                conv_id="test_conv_timeout_status",
            ))
            self.assertIn("unknown", status.content)
        finally:
            self.backend._commit_transaction_sync = original_commit
            tool.timeout_s = original_timeout

    async def test_write_exception_records_manual_review_without_account_change(self):
        conv_id = "test_conv_exception"
        before = self.user()
        await self.service.handle(self.request(
            "购买100分钟语音包",
            IntentCategory.BUSINESS_VOICE_PACK_PURCHASE,
            conv_id=conv_id,
        ))
        tool = self.tools._tools["purchase_product"]
        original_handler = tool.handler

        async def failing_handler(params, context):
            raise RuntimeError("simulated write failure")

        tool.handler = failing_handler
        try:
            result = await self.service.handle(self.request("确认购买", conv_id=conv_id))
            self.assertFalse(result.success)
            self.assertTrue(result.escalated)
            transactions = self.runtime_data()["transactions"]
            self.assertEqual(len(transactions), 1)
            self.assertEqual(transactions[0]["status"], "manual_review")
            self.assertEqual(transactions[0]["error_code"], "INTERNAL_ERROR")
            self.assertEqual(self.user()["balance_cents"], before["balance_cents"])
            self.assertEqual(self.user()["remaining_voice_minutes"], before["remaining_voice_minutes"])
        finally:
            tool.handler = original_handler

    async def test_timeout_fallback_covers_plan_change_and_recharge_without_mutation(self):
        before = self.user()
        cases = [
            (
                "change_plan",
                {"operation": "change_plan", "target_plan_id": "demo_plan_plus_79"},
                "change",
                7900,
            ),
            (
                "recharge_account",
                {"operation": "recharge_account", "amount_cents": 10000},
                "DEMO_RECHARGE",
                10000,
            ),
        ]
        for index, (tool_name, operation_params, expected_operation, expected_amount) in enumerate(cases):
            with self.subTest(tool_name=tool_name):
                conv_id = f"test_conv_fallback_{index}"
                context = {
                    "authenticated": True,
                    "authenticated_user_id": "demo_user_001",
                    "conv_id": conv_id,
                    "request_id": f"test_req_fallback_{index}",
                    "demo": True,
                }
                prepared = await self.tools.call(
                    "prepare_business_operation",
                    operation_params,
                    context,
                    use_cache=False,
                )
                confirmation = prepared.data["data"]
                await self.confirmations.confirm("demo_user_001", conv_id)
                params = {
                    **confirmation["normalized_params"],
                    "confirmation_id": confirmation["confirmation_id"],
                    "idempotency_key": f"test_fallback_key_{index}",
                }
                result = await self.backend.write_tool_fallback(
                    tool_name,
                    params,
                    context,
                    "执行超时",
                )
                self.assertFalse(result["success"])
                self.assertEqual(result["status"], "unknown")
                transaction = self.runtime_data()["transactions"][-1]
                self.assertEqual(transaction["operation"], expected_operation)
                self.assertEqual(transaction["amount_cents"], expected_amount)

        current = self.user()
        self.assertEqual(current["balance_cents"], before["balance_cents"])
        self.assertEqual(current["current_plan_id"], before["current_plan_id"])
        self.assertEqual(current["remaining_data_mb"], before["remaining_data_mb"])
        self.assertEqual(current["remaining_voice_minutes"], before["remaining_voice_minutes"])

    async def test_concurrent_vas_purchase_creates_only_one_subscription(self):
        before_balance = self.user()["balance_cents"]
        context_base = {
            "authenticated": True,
            "authenticated_user_id": "demo_user_001",
            "request_id": "test_req_concurrent_vas",
            "demo": True,
        }
        calls = []
        for index in range(2):
            conv_id = f"test_conv_concurrent_vas_{index}"
            context = {**context_base, "conv_id": conv_id}
            prepared = await self.tools.call(
                "prepare_business_operation",
                {"operation": "purchase_product", "product_id": "demo_vas_video_ringtone"},
                context,
                use_cache=False,
            )
            confirmation = prepared.data["data"]
            await self.confirmations.confirm("demo_user_001", conv_id)
            params = {
                **confirmation["normalized_params"],
                "confirmation_id": confirmation["confirmation_id"],
                "idempotency_key": f"test_concurrent_vas_key_{index}",
            }
            calls.append(self.tools.call("purchase_product", params, context, use_cache=False))

        results = await asyncio.gather(*calls)
        payloads = [result.data for result in results]
        self.assertEqual(sum(1 for payload in payloads if payload["success"]), 1)
        self.assertEqual(sum(1 for payload in payloads
                             if (payload.get("error") or {}).get("code") == "INVALID_STATE"), 1)
        self.assertEqual(len(self.runtime_data()["subscriptions"]), 1)
        self.assertEqual(len(self.runtime_data()["transactions"]), 1)
        self.assertEqual(self.user()["balance_cents"], before_balance - 500)

    async def test_revoked_token_is_not_authenticated(self):
        auth = await self.backend.authenticate(self.revoked_token)
        self.assertFalse(auth.authenticated)
        self.assertEqual(auth.error_code, "INVALID_TOKEN")

    async def test_expired_token_is_not_authenticated(self):
        data = self.runtime_data()
        token = next(item for item in data["mock_tokens"]
                     if item["token_value"] == self.active_tokens["demo_user_001"])
        token["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.backend._write_sync(data)
        auth = await self.backend.authenticate(self.active_tokens["demo_user_001"])
        self.assertFalse(auth.authenticated)
        self.assertEqual(auth.error_code, "INVALID_TOKEN")

    async def test_transactions_older_than_retention_are_pruned_on_initialize(self):
        data = self.runtime_data()
        data["transactions"].append({
            "transaction_id": "demo_tx_expired",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(),
        })
        self.backend._write_sync(data)
        await self.backend.initialize()
        self.assertFalse(any(t.get("transaction_id") == "demo_tx_expired"
                             for t in self.runtime_data()["transactions"]))


@unittest.skipUnless(os.getenv("ECHOMIND_TEST_REDIS_URL"), "需要独立的测试 Redis DB")
class BusinessRedisFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.seed = Path("data/demo_crm/mock_crm.json").resolve()
        self.runtime = Path(self.temp_dir.name) / "runtime.json"
        self.confirmations = RedisConfirmationStore(os.environ["ECHOMIND_TEST_REDIS_URL"])
        self.backend = MockCRMBackend(str(self.seed), str(self.runtime), self.confirmations)
        await self.backend.initialize()
        self.tools = MCPToolManager(api_key="test-api-key")
        register_mock_crm_tools(self.tools, self.backend)
        self.user_id = "demo_user_001"
        self.conv_id = f"test_redis_{uuid.uuid4().hex}"
        self.confirmation_id = None

    async def asyncTearDown(self):
        keys = [self.confirmations._pending_key(self.user_id, self.conv_id)]
        if self.confirmation_id:
            keys.append(self.confirmations._key(self.user_id, self.confirmation_id))
        await self.confirmations._redis.delete(*keys)
        await self.confirmations._redis.aclose()
        self.temp_dir.cleanup()

    async def test_redis_confirmation_supports_unknown_fallback_and_replay(self):
        context = {
            "authenticated": True,
            "authenticated_user_id": self.user_id,
            "conv_id": self.conv_id,
            "request_id": "test_req_redis_unknown",
            "demo": True,
        }
        before = json.loads(self.runtime.read_text(encoding="utf-8"))
        user_before = next(user for user in before["users"] if user["user_id"] == self.user_id)
        prepared = await self.tools.call(
            "prepare_business_operation",
            {"operation": "purchase_product", "product_id": "demo_voice_pack_100min_30d"},
            context,
            use_cache=False,
        )
        confirmation = prepared.data["data"]
        self.confirmation_id = confirmation["confirmation_id"]
        await self.confirmations.confirm(self.user_id, self.conv_id)
        params = {
            **confirmation["normalized_params"],
            "confirmation_id": self.confirmation_id,
            "idempotency_key": f"test_redis_unknown_{uuid.uuid4().hex}",
        }

        unknown = await self.backend.write_tool_fallback(
            "purchase_product", params, context, "执行超时"
        )
        self.assertEqual(unknown["status"], "unknown")
        record = await self.confirmations.get_record(self.user_id, self.confirmation_id)
        self.assertEqual(record["status"], "consumed")

        replay = await self.tools.call("purchase_product", params, context, use_cache=False)
        self.assertEqual(replay.data["status"], "unknown")
        self.assertEqual(replay.data["transaction_id"], unknown["transaction_id"])
        after = json.loads(self.runtime.read_text(encoding="utf-8"))
        user_after = next(user for user in after["users"] if user["user_id"] == self.user_id)
        self.assertEqual(user_after["balance_cents"], user_before["balance_cents"])
        self.assertEqual(user_after["remaining_voice_minutes"], user_before["remaining_voice_minutes"])
        self.assertEqual(len(after["transactions"]), 1)


if __name__ == "__main__":
    unittest.main()
