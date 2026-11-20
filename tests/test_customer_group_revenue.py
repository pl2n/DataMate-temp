import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from datamate.customer_group_revenue import execute_customer_group_revenue_share
from datamate.customer_group_revenue_total import execute_customer_group_revenue_total
from datamate.main import run
from datamate.metrics import Executor
from datamate.split_rules import SplitRules
from datamate.types import Table
from datamate.understanding import RulePlanner


class CustomerGroupRevenueShareTests(unittest.TestCase):
    def setUp(self):
        self.details = Table(
            "chi_tiet_don",
            ["Số CT", "Mã hàng bán", "Tiền bán"],
            [
                ["ORD1", "SP1", "50000"],
                ["ORD1", "SP2", "30000"],
                ["ORD2", "SP1", "100000"],
                ["ORD3", "SP2", "20000"],
            ],
            "chi_tiet_don.csv",
        )
        self.orders = Table(
            "don_hang",
            ["Số phiếu", "Mã khách mua", "Ngày bán", "Tình trạng đơn"],
            [
                ["ORD1", "KH1", "01/10/2025", "completed"],
                ["ORD2", "", "02/10/2025", "completed"],
                ["ORD3", "KH2", "03/10/2025", "cancelled"],
            ],
            "don_hang.csv",
        )
        self.customers = Table(
            "khach_hang",
            ["Mã khách lẻ/sỉ", "Nhóm"],
            [["KH1", "thân thiết"], ["KH2", "thường"]],
            "khach_hang.csv",
        )
        self.tables = [self.details, self.orders, self.customers]
        self.rules = replace(
            SplitRules.test_defaults(),
            revenue_supported=True,
            revenue_amount_basis="line_amount_after_line_discount",
            revenue_period_basis="order_date",
            revenue_excluded_statuses=frozenset(
                {"cancelled", "returned", "delivery_failed"}
            ),
            revenue_included_statuses=frozenset({"in_transit"}),
            deduplicate_identical_order_lines=True,
        )

    def run_query(self, tables=None, rules=None, group="thân thiết"):
        return execute_customer_group_revenue_share(
            tables or self.tables,
            rules or self.rules,
            "2025-10-01",
            "2025-10-31",
            group,
        )

    def test_actual_rulebook_clauses_enable_required_revenue_policies(self):
        rule_text = """
| Đơn tính vào doanh thu | đơn không huỷ và không trả hàng. Đơn có trả hàng, kể cả chỉ trả một phần, bỏ cả đơn. Đơn đang giao vẫn tính |
| Bán được bao nhiêu tiền, thu về bao nhiêu tiền | là doanh thu theo mục này, không phải tiền khách đã trả |
| Đơn thuộc kỳ nào | theo ngày đặt, không theo ngày giao hay ngày thu tiền |
| Doanh thu một đơn | tổng thành tiền các dòng hàng (đã trừ giảm giá trên từng dòng) |
| Hai dòng của cùng một đơn giống nhau ở mọi ô | lỗi xuất file, tính một lần |
| Bán chạy | theo số lượng quy về đơn vị cơ bản |
| Tỉ lệ đơn huỷ trong kỳ | phần trăm đơn huỷ trong mọi đơn đặt trong kỳ |
- Bằng nhau: hai đối tượng bằng nhau ở tiêu chí câu hỏi thì xếp theo mã tăng dần (không có mã thì theo tên).
"""
        parsed = SplitRules.from_text(rule_text)
        self.assertTrue(parsed.revenue_supported)
        self.assertEqual(parsed.revenue_amount_basis, "line_amount_after_line_discount")
        self.assertEqual(parsed.revenue_period_basis, "order_date")
        self.assertTrue({"cancelled", "returned", "delivery_failed"}.issubset(
            parsed.revenue_excluded_statuses
        ))
        self.assertIn("in_transit", parsed.revenue_included_statuses)
        self.assertTrue(parsed.deduplicate_identical_order_lines)

    def test_question_planner_and_executor_run_the_allowlisted_query_family(self):
        question = (
            "Tỷ trọng doanh thu khách hàng thuộc nhóm thân thiết tháng 10/2025"
        )
        planner = RulePlanner(split_rules=self.rules)
        spec = planner.interpret(question, "2025-11-01", "biz_129")
        self.assertEqual(spec.intent, "customer_group_revenue_share")
        self.assertEqual(spec.dimensions, ("customer_group",))
        self.assertEqual(spec.filters, (("customer_group", "thân thiết"),))
        self.assertEqual(spec.unit, "percent")
        self.assertTrue(spec.executable)

        plan = planner.plan(question, "2025-11-01", "biz_129")
        self.assertEqual(plan.intent, "customer_group_revenue_share")
        self.assertEqual(plan.filters, (("customer_group", "thân thiết"),))
        candidate, reason = Executor(self.tables, rules=self.rules).execute_with_reason(
            plan, question, spec=spec
        )
        self.assertIsNone(reason)
        self.assertEqual(candidate["answer"], 44.44)

    def test_exact_contest_wordings_resolve_only_the_share_questions(self):
        planner = RulePlanner(split_rules=self.rules)
        questions = (
            "Trong tổng doanh thu tháng 10/2025, phần của khách nhóm thân thiết là mấy phần trăm?",
            "Tỉ trọng doanh thu của khách nhóm thân thiết trong tổng doanh thu tháng 6/2025 là bao nhiêu phần trăm?",
        )
        for question in questions:
            with self.subTest(question=question):
                spec = planner.interpret(question, "2026-08-14", "biz_129")
                self.assertEqual(spec.intent, "customer_group_revenue_share")
                self.assertTrue(spec.executable)
                self.assertEqual(dict(spec.filters)["customer_group"], "thân thiết")

    def test_group_revenue_amount_questions_do_not_drop_the_customer_filter(self):
        planner = RulePlanner(split_rules=self.rules)
        questions = (
            "tháng 3/2025, các khách thuoocj nhóm thân thiết mua total bao nhieeu tiền hàng",
            "Cho tôi biết doanh thu các đơn của khách nhóm thân thiết tháng 6/2025.",
        )
        for question in questions:
            with self.subTest(question=question):
                spec = planner.interpret(question, "2026-08-14", "biz_129")
                self.assertFalse(spec.executable)

    def test_other_businesses_cannot_enable_this_contest_specific_query_family(self):
        planner = RulePlanner(split_rules=self.rules)
        question = "Tỷ trọng doanh thu nhóm thân thiết tháng 10/2025"
        spec = planner.interpret(question, "2025-11-01", "biz_other")
        self.assertEqual(spec.intent, "customer_group_revenue_share")
        self.assertFalse(spec.executable)
        plan = planner.plan(question, "2025-11-01", "biz_other")
        self.assertIsNone(plan)

    def test_other_known_customer_groups_can_be_resolved_explicitly(self):
        planner = RulePlanner(split_rules=self.rules)
        for group in ("lẻ", "sỉ"):
            with self.subTest(group=group):
                spec = planner.interpret(
                    f"Tỷ trọng doanh thu nhóm {group} tháng 10/2025",
                    "2025-11-01",
                    "biz_129",
                )
                self.assertEqual(spec.intent, "customer_group_revenue_share")
                self.assertEqual(dict(spec.filters)["customer_group"], group)

    def test_full_main_pipeline_writes_the_percentage_answer(self):
        rule_text = """# Rulebook
| Đơn tính vào doanh thu | đơn không huỷ và không trả hàng. Đơn có trả hàng, kể cả chỉ trả một phần, bỏ cả đơn. Đơn đang giao vẫn tính |
| Bán được bao nhiêu tiền, thu về bao nhiêu tiền | là doanh thu theo mục này, không phải tiền khách đã trả |
| Đơn thuộc kỳ nào | theo ngày đặt, không theo ngày giao hay ngày thu tiền |
| Doanh thu một đơn | tổng thành tiền các dòng hàng (đã trừ giảm giá trên từng dòng) |
| Hai dòng của cùng một đơn giống nhau ở mọi ô | lỗi xuất file, tính một lần |
| Bán chạy | theo số lượng quy về đơn vị cơ bản |
| Tỉ lệ đơn huỷ trong kỳ | phần trăm đơn huỷ trong mọi đơn đặt trong kỳ |
- Bằng nhau: hai đối tượng bằng nhau ở tiêu chí câu hỏi thì xếp theo mã tăng dần (không có mã thì theo tên).
"""
        parsed = SplitRules.from_text(rule_text)
        self.assertTrue(parsed.revenue_supported)
        self.assertTrue(parsed.ranking_default)
        self.assertTrue(parsed.tie_breaker)
        self.assertTrue(parsed.cancellation_numerator_statuses)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data" / "biz_129"
            data.mkdir(parents=True)
            sources = {
                "chi_tiet_don.csv": (
                    ["Số CT", "Mã hàng bán", "Tiền bán"],
                    [
                        ["ORD1", "SP1", "50000"],
                        ["ORD1", "SP2", "30000"],
                        ["ORD2", "SP1", "100000"],
                        ["ORD3", "SP2", "20000"],
                    ],
                ),
                "don_hang.csv": (
                    ["Số phiếu", "Mã khách mua", "Ngày bán", "Tình trạng đơn"],
                    [
                        ["ORD1", "KH1", "2025-10-01", "completed"],
                        ["ORD2", "", "2025-10-02", "completed"],
                        ["ORD3", "KH2", "2025-10-03", "returned"],
                    ],
                ),
                "khach_hang.csv": (
                    ["Mã khách lẻ/sỉ", "Nhóm"],
                    [["KH1", "thân thiết"], ["KH2", "sỉ"]],
                ),
            }
            for filename, (headers, rows) in sources.items():
                with (data / filename).open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(headers)
                    writer.writerows(rows)
            (root / "rulebook.md").write_text(rule_text, encoding="utf-8")
            (root / "questions.jsonl").write_text(
                json.dumps({
                    "id": "q_share",
                    "business_id": "biz_129",
                    "question": "Trong tổng doanh thu tháng 10/2025, phần của khách nhóm thân thiết là mấy phần trăm?",
                    "as_of_date": "2026-08-14",
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            output = root / "answers.jsonl"
            run(root, output, log_directory=root / "logs")
            record = json.loads(output.read_text(encoding="utf-8").strip())
            trace = json.loads(
                (root / "logs" / "trace.jsonl").read_text(encoding="utf-8").strip()
            )

        self.assertEqual(record, {
            "id": "q_share",
            "type": "percent",
            "answer": 44.44,
        }, trace)

    def test_unrecognized_customer_group_does_not_become_a_generic_category_share(self):
        planner = RulePlanner(split_rules=self.rules)
        spec = planner.interpret(
            "Tỷ trọng doanh thu nhóm VIP tháng 10/2025",
            "2025-11-01",
            "biz_129",
        )
        self.assertNotEqual(spec.intent, "customer_group_revenue_share")
        self.assertFalse(spec.executable)

    def test_guest_sales_stay_in_whole_shop_denominator(self):
        candidate, reason = self.run_query()
        self.assertIsNone(reason)
        self.assertEqual(candidate["answer"], 44.44)
        self.assertEqual(candidate["type"], "percent")
        self.assertIn("left_join_preserves_guest_revenue", candidate["evidence"])

    def test_guest_only_period_contributes_zero_to_group_numerator(self):
        orders = Table(
            self.orders.name,
            self.orders.headers,
            [
                ["ORD1", "KH1", "01/09/2025", "completed"],
                ["ORD2", "", "02/10/2025", "completed"],
                ["ORD3", "KH2", "03/09/2025", "cancelled"],
            ],
            self.orders.source,
        )
        candidate, reason = self.run_query(
            [self.details, orders, self.customers]
        )
        self.assertIsNone(reason)
        self.assertEqual(candidate["answer"], 0.0)

    def test_exact_duplicate_lines_in_same_order_count_once(self):
        details = Table(
            self.details.name,
            self.details.headers,
            self.details.rows + [self.details.rows[0]],
            self.details.source,
        )
        candidate, reason = self.run_query([details, self.orders, self.customers])
        self.assertIsNone(reason)
        self.assertEqual(candidate["answer"], 44.44)

    def test_identical_line_values_in_different_orders_are_not_deduplicated(self):
        details = Table(
            self.details.name,
            self.details.headers,
            self.details.rows + [["ORD2", "SP1", "50000"]],
            self.details.source,
        )
        candidate, reason = self.run_query([details, self.orders, self.customers])
        self.assertIsNone(reason)
        # The added guest-order line increases only the whole-shop denominator.
        self.assertEqual(candidate["answer"], 34.78)

    def test_requires_explicit_duplicate_line_policy(self):
        rules = replace(self.rules, deduplicate_identical_order_lines=False)
        candidate, reason = self.run_query(rules=rules)
        self.assertIsNone(candidate)
        self.assertEqual(reason, "rulebook_unavailable")

    def test_in_transit_orders_are_included_when_rulebook_says_so(self):
        orders = Table(
            self.orders.name,
            self.orders.headers,
            [
                ["ORD1", "KH1", "01/10/2025", "in transit"],
                ["ORD2", "", "02/10/2025", "completed"],
                ["ORD3", "KH2", "03/10/2025", "cancelled"],
            ],
            self.orders.source,
        )
        candidate, reason = self.run_query([self.details, orders, self.customers])
        self.assertIsNone(reason)
        self.assertEqual(candidate["answer"], 44.44)

    def test_returned_order_is_excluded_in_full(self):
        orders = Table(
            self.orders.name,
            self.orders.headers,
            [
                ["ORD1", "KH1", "01/10/2025", "completed"],
                ["ORD2", "", "02/10/2025", "completed"],
                ["ORD3", "KH2", "03/10/2025", "returned"],
            ],
            self.orders.source,
        )
        candidate, reason = self.run_query([self.details, orders, self.customers])
        self.assertIsNone(reason)
        self.assertEqual(candidate["answer"], 44.44)

    def test_requires_rulebook_in_transit_revenue_policy(self):
        rules = replace(self.rules, revenue_included_statuses=frozenset())
        candidate, reason = self.run_query(rules=rules)
        self.assertIsNone(candidate)
        self.assertEqual(reason, "rulebook_unavailable")

    def test_rejects_missing_customer_group_mapping(self):
        customers = Table(
            self.customers.name, ["Mã khách lẻ/sỉ", "Phân loại"],
            self.customers.rows, self.customers.source,
        )
        candidate, reason = self.run_query(
            [self.details, self.orders, customers]
        )
        self.assertIsNone(candidate)
        self.assertEqual(reason, "missing_required_fields")

    def test_rejects_wrong_source_role_even_with_matching_headers(self):
        renamed = Table(
            self.details.name, self.details.headers, self.details.rows,
            "sales.csv",
        )
        candidate, reason = self.run_query([renamed, self.orders, self.customers])
        self.assertIsNone(candidate)
        self.assertEqual(reason, "source_scope_mismatch")

    def test_rejects_unmatched_nonblank_customer_key(self):
        orders = Table(
            self.orders.name, self.orders.headers,
            [
                ["ORD1", "KH404", "01/10/2025", "completed"],
                ["ORD2", "", "02/10/2025", "completed"],
                ["ORD3", "KH2", "03/10/2025", "cancelled"],
            ],
            self.orders.source,
        )
        candidate, reason = self.run_query([self.details, orders, self.customers])
        self.assertIsNone(candidate)
        self.assertEqual(reason, "relationship_not_validated")

    def test_rejects_unknown_order_status_in_requested_period(self):
        orders = Table(
            self.orders.name, self.orders.headers,
            [
                ["ORD1", "KH1", "01/10/2025", "mystery"],
                ["ORD2", "", "02/10/2025", "completed"],
                ["ORD3", "KH2", "03/10/2025", "cancelled"],
            ],
            self.orders.source,
        )
        candidate, reason = self.run_query([self.details, orders, self.customers])
        self.assertIsNone(candidate)
        self.assertEqual(reason, "unverified_order_status")

    def test_rejects_missing_or_unverified_revenue_rule_semantics(self):
        rules = replace(self.rules, revenue_period_basis="sales_date")
        candidate, reason = self.run_query(rules=rules)
        self.assertIsNone(candidate)
        self.assertEqual(reason, "rulebook_unavailable")


    def test_customer_group_revenue_total_returns_only_the_requested_group(self):
        candidate, reason = execute_customer_group_revenue_total(
            self.tables, self.rules, "2025-10-01", "2025-10-31", "thân thiết"
        )
        self.assertIsNone(reason)
        self.assertEqual(candidate["type"], "number")
        self.assertEqual(candidate["answer"], 80000.0)

    def test_exact_contest_group_revenue_total_questions_are_executable(self):
        planner = RulePlanner(split_rules=self.rules)
        questions = (
            "tháng 3/2025, các khách thuoocj nhóm thân thiết mua total bao nhieeu tiền hàng",
            "Cho tôi biết doanh thu các đơn của khách nhóm thân thiết tháng 6/2025.",
        )
        for question in questions:
            with self.subTest(question=question):
                spec = planner.interpret(question, "2026-08-14", "biz_129")
                self.assertEqual(spec.intent, "customer_group_revenue_total")
                self.assertTrue(spec.executable)
                self.assertEqual(dict(spec.filters)["customer_group"], "thân thiết")
                self.assertEqual(spec.unit, "VND")
                self.assertEqual(planner.plan(question, "2026-08-14", "biz_129").intent,
                                 "customer_group_revenue_total")

    def test_customer_group_revenue_total_is_scoped_to_biz_129(self):
        planner = RulePlanner(split_rules=self.rules)
        question = "Doanh thu khách nhóm thân thiết tháng 6/2025"
        spec = planner.interpret(question, "2026-08-14", "biz_other")
        self.assertEqual(spec.intent, "customer_group_revenue_total")
        self.assertFalse(spec.executable)
        self.assertIsNone(planner.plan(question, "2026-08-14", "biz_other"))



if __name__ == "__main__":
    unittest.main()
