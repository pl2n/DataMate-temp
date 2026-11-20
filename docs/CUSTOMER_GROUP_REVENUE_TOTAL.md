# Customer-group revenue total — biz_129

## Supported questions

This query family returns the revenue amount attributable to one explicitly named customer group:

- `q_635440e343cc`: total March 2025 sales for customers in group `thân thiết`.
- `q_d361c00c6829`: revenue of orders belonging to customers in group `thân thiết` in June 2025.

It is separate from `customer_group_revenue_share`: these questions request a money amount, not a percentage.

## Calculation contract

```text
customer_group_revenue =
    sum(eligible net sales-line amount
        where joined customer group equals the requested group)
```

The executor uses the reviewed `biz_129` source roles and sales-line fact grain:

- `chi_tiet_don.csv`: sales-line fact and net amount `Tiền bán`
- `don_hang.csv`: order date, order status, customer ID
- `khach_hang.csv`: customer ID and group

It applies order-date scope, line-level net amount, full-order exclusion for cancelled/returned orders, inclusion of in-transit orders, and exact duplicate-line deduplication. The LEFT JOIN preserves the sales-line grain, but guest orders and customers without a group do not enter the requested group's total.

Payment events are not joined to sales lines. They are a separate fact with multiple payment events per order and require their own aggregation semantics.

## Guardrails

- Enabled only for business `biz_129`.
- Requires one exact table for each documented source role and the same validated two-hop non-fanout path.
- Requires the requested group to exist in the customer dimension.
- Returns a numeric money amount (`number` with VND unit in the interpreted query specification), not a percentage.
- Unknown statuses, invalid dates/amounts, unmatched keys, missing fields, ambiguous joins, unsupported rulebook semantics, or zero eligible revenue fail closed.
- The existing revenue-share intent remains unchanged and continues to include guest sales only in its whole-shop denominator.
