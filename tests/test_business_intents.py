import unittest

from core.intent_recognizer import IntentCategory, classify_business_intent
from evaluation.evaluator import DEFAULT_INTENT_CASES


class BusinessIntentTests(unittest.TestCase):
    def test_confirmed_business_intents(self):
        cases = {
            "我还有多少流量？": IntentCategory.BUSINESS_ACCOUNT_QUERY,
            "有哪些5G套餐？": IntentCategory.BUSINESS_PLAN_QUERY,
            "现在有哪些Demo套餐？": IntentCategory.BUSINESS_PLAN_QUERY,
            "每月需要30GB，有推荐吗？": IntentCategory.BUSINESS_PLAN_RECOMMENDATION,
            "帮我换成79元套餐": IntentCategory.BUSINESS_PLAN_CHANGE,
            "我要退订当前套餐": IntentCategory.BUSINESS_PLAN_UNSUBSCRIBE,
            "有哪些流量包？": IntentCategory.BUSINESS_PRODUCT_QUERY,
            "给我购买30GB流量包": IntentCategory.BUSINESS_DATA_PACK_PURCHASE,
            "购买300分钟语音包": IntentCategory.BUSINESS_VOICE_PACK_PURCHASE,
            "开通视频彩铃": IntentCategory.BUSINESS_VAS_ACTIVATION,
            "给Demo账户充值100元": IntentCategory.BUSINESS_ACCOUNT_RECHARGE,
            "刚才办理成功了吗？": IntentCategory.BUSINESS_TRANSACTION_STATUS,
            "我想了解宽带安装": IntentCategory.BUSINESS_BROADBAND_QUERY,
            "我要开国际漫游": IntentCategory.BUSINESS_MANUAL_SERVICE,
            "宽带可以迁移地址吗？": IntentCategory.BUSINESS_MANUAL_SERVICE,
            "我要办理一个新的5G套餐": IntentCategory.BUSINESS_PLAN_CHANGE,
            "我的话费余额还有多少？": IntentCategory.BUSINESS_ACCOUNT_QUERY,
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(classify_business_intent(message), expected)

    def test_complaint_remains_generic_escalation_boundary(self):
        self.assertIsNone(classify_business_intent("我要投诉，转人工客服"))

    def test_default_business_evaluation_cases_use_deterministic_route(self):
        cases = [case for case in DEFAULT_INTENT_CASES if case.expected_intent.startswith("business_")]
        self.assertEqual(len(cases), 13)
        for case in cases:
            with self.subTest(message=case.message):
                predicted = classify_business_intent(case.message)
                self.assertIsNotNone(predicted)
                self.assertEqual(predicted.value, case.expected_intent)


if __name__ == "__main__":
    unittest.main()
