"""Narrow executor for Contest biz_129 customer-group revenue totals by customer group.

This is intentionally not a generic dimension join or arbitrary GROUP BY engine.
It accepts only the README-documented three-source shape and the reviewed
revenue semantics for this query family.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import PurePosixPath

from .join_contracts import build_fact_join_contract
from .join_executor import execute_fact_join_contract
from .normalization import infer_decimal_separator, parse_date, parse_decimal
from .normalise import fold
from .relationship_paths import resolve_relationship_path
from .relationships import discover_relationships
from .rules import classify_order_status
from .semantic import map_table_schema


_REQUIRED_EXCLUDED_STATUSES = {"cancelled", "returned", "delivery_failed"}
_SOURCE_ROLES = {
    "chi_tiet_don.csv": "fact",
    "don_hang.csv": "order",
    "khach_hang.csv": "customer",
}


def _source_basename(table):
    return PurePosixPath(str(table.source).replace("\\", "/")).name.casefold()


def _role_tables(tables):
    selected = {role: [] for role in _SOURCE_ROLES.values()}
    for table in tables:
        role = _SOURCE_ROLES.get(_source_basename(table))
        if role is not None:
            selected[role].append(table)
    if any(len(selected[role]) != 1 for role in selected):
        return None
    return {role: selected[role][0] for role in selected}


def _mapped_index(schema, field):
    index = schema.mapped_fields.get(field)
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    return index


def _decimal(value, separator):
    parsed = parse_decimal(value, decimal_separator=separator)
    return parsed.value if parsed.ok and parsed.value.is_finite() else None


def _date(value, date_system):
    parsed = parse_date(
        value,
        day_first=True,
        excel_date_system=date_system,
    )
    return parsed.value if parsed.ok else None


def execute_customer_group_revenue_total(tables, rules, start, end, customer_group):
    """Return a verified customer-group revenue amount candidate, or (None, reason_code)."""
    if (
        rules is None
        or not rules.revenue_supported
        or rules.revenue_amount_basis != "line_amount_after_line_discount"
        or rules.revenue_period_basis != "order_date"
        or not _REQUIRED_EXCLUDED_STATUSES.issubset(rules.revenue_excluded_statuses)
        or "in_transit" not in rules.revenue_included_statuses
        or not rules.deduplicate_identical_order_lines
    ):
        return None, "rulebook_unavailable"
    if not isinstance(customer_group, str) or not customer_group.strip():
        return None, "unresolved_filter"
    try:
        start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        return None, "temporal_scope_not_executable"
    if start_date > end_date:
        return None, "temporal_scope_not_executable"

    role_tables = _role_tables(tables)
    if role_tables is None:
        return None, "source_scope_mismatch"
    fact, orders, customers = (
        role_tables["fact"], role_tables["order"], role_tables["customer"]
    )
    # Rulebook §8: exact duplicate lines within the same order are export
    # errors and count once. The order key is part of the row, so identical
    # rows belonging to different orders remain distinct sales.
    unique_rows = []
    seen_rows = set()
    for row in fact.rows:
        row_key = tuple((type(value).__name__, repr(value)) for value in row)
        if row_key in seen_rows:
            continue
        seen_rows.add(row_key)
        unique_rows.append(row)
    fact = replace(fact, rows=unique_rows)
    schemas = {
        role: map_table_schema(table)
        for role, table in role_tables.items()
    }

    fact_amount = _mapped_index(schemas["fact"], "sales_line_amount")
    fact_order_key = _mapped_index(schemas["fact"], "order_id")
    order_key = _mapped_index(schemas["order"], "order_id")
    order_customer_key = _mapped_index(schemas["order"], "customer_id")
    order_date = _mapped_index(schemas["order"], "order_date")
    order_status = _mapped_index(schemas["order"], "order_status")
    customer_key = _mapped_index(schemas["customer"], "customer_id")
    customer_group_column = _mapped_index(schemas["customer"], "customer_group")

    required = (
        fact_amount, fact_order_key, order_key, order_customer_key,
        order_date, order_status, customer_key, customer_group_column,
    )
    if any(index is None for index in required):
        return None, "missing_required_fields"

    relationships = discover_relationships([fact, orders, customers])
    path = resolve_relationship_path(
        relationships,
        (fact.name, fact.source),
        (customers.name, customers.source),
        max_hops=2,
    )
    if path.status not in {"unique_safe", "left_join_required"}:
        return None, "relationship_not_validated"
    contract = build_fact_join_contract(
        path,
        (fact.name, fact.source),
        (customers.name, customers.source),
        fact_grain="one row per sales order detail line",
        measure_field=str(fact.headers[fact_amount]),
        measure_column_index=fact_amount,
        join_type="left",
    )
    if contract is None or len(contract.path_hops) != 2:
        return None, "join_contract_invalid"
    if (
        contract.path_hops[0].canonical_keys != ("order_id",)
        or contract.path_hops[1].canonical_keys != ("customer_id",)
        or contract.path_hops[0].to_table != (orders.name, orders.source)
        or contract.path_hops[1].from_table != (orders.name, orders.source)
    ):
        return None, "join_contract_invalid"

    joined = execute_fact_join_contract([fact, orders, customers], contract)
    if joined is None or joined.row_count != len(fact.rows):
        return None, "join_execution_failed"

    order_identity = (orders.name, orders.source)
    customer_identity = (customers.name, customers.source)
    joined_dates = joined.column(order_identity, order_date)
    joined_statuses = joined.column(order_identity, order_status)
    joined_groups = joined.column(customer_identity, customer_group_column)
    if any(value is None for value in (joined_dates, joined_statuses, joined_groups)):
        return None, "join_result_incomplete"
    if len(joined_dates) != len(fact.rows):
        return None, "join_result_incomplete"

    amount_separator = infer_decimal_separator(
        row[fact_amount] for row in fact.rows if fact_amount < len(row)
    )
    denominator = Decimal(0)
    numerator = Decimal(0)
    eligible_rows = 0
    wanted_group = fold(customer_group)
    known_groups = {
        fold(row[customer_group_column])
        for row in customers.rows
        if customer_group_column < len(row)
        and row[customer_group_column] is not None
        and str(row[customer_group_column]).strip()
    }
    if wanted_group not in known_groups:
        return None, "unresolved_filter"

    for index, fact_row in enumerate(fact.rows):
        if fact_amount >= len(fact_row):
            return None, "malformed_fact_row"
        day = _date(joined_dates[index], orders.date_system)
        if day is None:
            return None, "invalid_order_date"
        if not start_date <= day <= end_date:
            continue

        status_class = classify_order_status(joined_statuses[index])
        if status_class in rules.revenue_excluded_statuses:
            continue
        if status_class in rules.revenue_included_statuses or status_class == "successful":
            pass
        elif status_class in {"pending", "in_transit"}:
            return None, "unverified_order_status"
        else:
            return None, "unverified_order_status"

        amount = _decimal(fact_row[fact_amount], amount_separator)
        if amount is None or amount < 0:
            return None, "invalid_revenue_amount"
        denominator += amount
        eligible_rows += 1
        group_value = joined_groups[index]
        # Guest orders and customers without a group remain in the whole-shop
        # denominator but can never be attributed to the requested group.
        if group_value is not None and fold(group_value) == wanted_group:
            numerator += amount

    if eligible_rows == 0 or denominator <= 0:
        return None, "no_eligible_revenue"
    percentage = (numerator * Decimal(100) / denominator).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return {
        "type": "number",
        "answer": float(numerator),
        "evidence": [
            fact.source,
            orders.source,
            customers.source,
            "left_join_preserves_fact_rows",
            "customer_group_revenue_numerator",
        ],
    }, None
