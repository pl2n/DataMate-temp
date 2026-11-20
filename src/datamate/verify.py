"""Verification firewall: only exact schema-safe, evidenced values pass."""
from .ingest import IngestionError
from .output import valid_record
from .split_rules import RulebookError
import math

REASON_CODES = frozenset({
    "unsupported_intent",
    "ambiguous_entity",
    "missing_time_range",
    "missing_column",
    "parse_failure",
    "source_unavailable",
    "invalid_unit",
    "join_unsafe",
    "insufficient_evidence",
    "no_data",
    "missing_order_status",
    "unknown_order_status",
    "conflicting_order_status",
    "verification_failed",
    "rulebook_unavailable",
})


def verify_with_reason(question_id, candidate, plan, *, spec=None, error=None, execution_reason=None):
    """Return the contract-safe answer plus internal trace decision metadata."""
    def abstain(reason_code):
        assert reason_code in REASON_CODES
        return (
            {"id": question_id, "type": "abstain"},
            {"status": "abstained", "reason_code": reason_code},
        )

    if isinstance(error, FileNotFoundError):
        return abstain("source_unavailable")
    if isinstance(error, IngestionError):
        return abstain("parse_failure")
    if isinstance(error, RulebookError):
        return abstain("rulebook_unavailable")
    if error is not None:
        return abstain("verification_failed")

    if spec is not None:
        if "entity_unresolved" in spec.ambiguity_flags:
            return abstain("ambiguous_entity")
        if spec.unsupported_reason == "temporal_scope_not_executable":
            return abstain("missing_time_range")
        if not spec.executable:
            return abstain("unsupported_intent")
    if plan is None:
        return abstain("unsupported_intent")
    if execution_reason is not None:
        return abstain(execution_reason)
    if candidate is None or not candidate.get("evidence"):
        return abstain("insufficient_evidence")
    if not isinstance(plan.confidence, (int, float)) or not math.isfinite(plan.confidence) or not 0.5 <= plan.confidence <= 1:
        return abstain("verification_failed")
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list) or not evidence or any(not isinstance(item, str) or not item.strip() for item in evidence):
        return abstain("verification_failed")
    expected_type = {
        "revenue": "number",
        "collected_amount": "number",
        "quantity": "number",
        "order_count": "number",
        "cancellation_rate": "percent",
        "customer_group_revenue_share": "percent",
        "customer_group_revenue_total": "number",
        "daily_revenue_threshold_count": "number",
        "order_revenue_threshold_count": "number",
    }.get(plan.intent)
    if plan.intent == "sales_ranking":
        expected_type = "string" if plan.top_k == 1 else "list"
    if expected_type is None or candidate.get("type") != expected_type:
        return abstain("verification_failed")
    if plan.intent == "sales_ranking":
        answer = candidate.get("answer")
        if plan.top_k == 1:
            if not isinstance(answer, str) or not answer.strip():
                return abstain("verification_failed")
        elif not isinstance(answer, list) or not answer or len(answer) > plan.top_k:
            # The reference contract returns every available candidate when
            # fewer than k exist, so a short non-empty list is valid.
            return abstain("verification_failed")
    record = {"id": question_id, "type": candidate["type"], "answer": candidate["answer"]}
    if not valid_record(record):
        return abstain("verification_failed")
    return record, {"status": "answered", "reason_code": None}


def verify(question_id, candidate, plan):
    """Backward-compatible output-only verifier API."""
    return verify_with_reason(question_id, candidate, plan)[0]
