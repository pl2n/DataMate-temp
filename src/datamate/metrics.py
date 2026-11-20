import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

from .customer_group_revenue import execute_customer_group_revenue_share
from .customer_group_revenue_total import execute_customer_group_revenue_total
from .normalization import infer_decimal_separator, parse_date, parse_decimal
from .normalise import fold, tokens
from .rules import classify_order_status, classify_payment_status
from .split_rules import SplitRules
from .types import Table

DATE = ("ngay dat", "ngay ban", "ngay tao", "ngay lap", "ngay")
LINE_AMOUNT = (
    "thanh tien", "tien hang", "tien ban", "line amount", "line amounts",
    "line amount after discount", "sales amount", "amount",
)
COLLECTED_AMOUNT = ("gia tri", "so tien", "tien", "amount", "value", "payment amount")
COLLECTION_DATE = ("ngay thu", "ngay thanh toan", "thoi diem", "payment date", "date received", "paid at", "collection date")
# Prefer normalized/base-unit quantity whenever a workbook exposes it.  The
# raw sold quantity may still be in packaging units (box, bottle, etc.).
BASE_QUANTITY = (
    "sl le", "so luong le", "so luong co ban", "sl co ban",
    "sl quy doi", "slquydoi", "quy ra dv le", "quy ra don vi le", "base quantity",
)
QUANTITY = (
    *BASE_QUANTITY,
    "so luong", "so luong ban", "sl", "quantity",
)
ORDER = (
    "ma don", "so don", "ma hoa don", "so hoa don", "so phieu", "ma chung tu",
    "mahoadon", "sohoadon", "ma giao dich", "order id", "invoice id", "ma gd",
)
STATUS = ("trang thai", "status")
SPECIFIC_ORDER_STATUS = (
    "trang thai don hang", "trang thai don", "tinh trang don hang", "tinh trang don",
    "trang thai xu ly", "ket qua", "ghi chu tt", "xu ly",
)
GENERIC_ORDER_STATUS = ("trang thai", "tinh trang", "tinhtrang", "status")
PRODUCT = ("ten hang", "ten san pham", "ten mat hang", "ten mon", "ten sp", "ten goi", "chi tiet hang", "mon")
PRODUCT_EXACT = (*PRODUCT, "san pham", "hang hoa", "hang ban", "mat hang")


def _column(headers, choices):
    columns = [fold(x) for x in headers]
    compact_columns = [column.replace(" ", "") for column in columns]
    for choice in choices:
        if choice in columns:
            return columns.index(choice)
    for choice in choices:
        compact_choice = fold(choice).replace(" ", "")
        if compact_choice in compact_columns:
            return compact_columns.index(compact_choice)
    for choice in choices:
        for index, column in enumerate(columns):
            if choice in column:
                return index
    return None


def _exact_column(headers, choices):
    """Match a documented metric header exactly; avoid substring false positives."""
    columns = [fold(x) for x in headers]
    compact_columns = [column.replace(" ", "") for column in columns]
    for choice in choices:
        if choice in columns:
            return columns.index(choice)
    for choice in choices:
        compact_choice = fold(choice).replace(" ", "")
        if compact_choice in compact_columns:
            return compact_columns.index(compact_choice)
    return None


def _order_status_column(headers):
    """Match documented status headers exactly; never match customer/invoice status substrings."""
    columns = [fold(header) for header in headers]
    specific = [columns.index(name) for name in SPECIFIC_ORDER_STATUS if name in columns]
    if len(specific) == 1:
        return specific[0]
    if specific:
        return None
    generic = [columns.index(name) for name in GENERIC_ORDER_STATUS if name in columns]
    return generic[0] if len(generic) == 1 else None


def _product_column(headers):
    """Find a descriptive product label, never a date/code/category substring."""
    columns = [fold(header) for header in headers]
    for choice in PRODUCT_EXACT:
        if choice in columns:
            return columns.index(choice)
    compact_columns = [column.replace(" ", "") for column in columns]
    for choice in PRODUCT_EXACT:
        compact_choice = fold(choice).replace(" ", "")
        if compact_choice in compact_columns:
            return compact_columns.index(compact_choice)
    for index, column in enumerate(columns):
        if any(marker in column.split() for marker in ("ma", "id", "code", "sku", "ngay", "date", "so")):
            continue
        if any(choice in column for choice in PRODUCT):
            return index
    return None


@lru_cache(maxsize=8192)
def _is_summary_label(value):
    """Recognize exported subtotal labels; repeated product names stay cheap."""
    words = fold(value).split()
    if not words:
        return False
    if words[0] in {"subtotal", "total"}:
        return True
    return len(words) > 1 and words[0] == "tong" and words[1] in {
        "ngay", "thang", "tuan", "quy", "nam", "cong", "doanh", "tien",
    }


def _is_summary_row(row, product_column):
    """Recognize exported subtotal rows that resemble order line items."""
    if product_column is None or product_column >= len(row):
        return False
    return _is_summary_label(str(row[product_column] or ""))


def _is_payment_table(table):
    role = fold(f"{table.name} {table.source}")
    return any(term in role for term in ("thanh toan", "phieu thu", "payment", "receipt"))


def _payment_grouped_column(headers, leaf_aliases):
    """Resolve a leaf header only inside an explicit payment group."""
    candidates = []
    allowed_groups = {"thanh toan", "lich su thanh toan", "payment"}
    for index, header in enumerate(headers):
        raw = str(header or "")
        if " / " not in raw:
            continue
        group, leaf = raw.rsplit(" / ", 1)
        if fold(group) in allowed_groups and fold(leaf) in leaf_aliases:
            candidates.append(index)
    return candidates[0] if len(candidates) == 1 else None


def _payment_status_column(headers):
    """Resolve only an explicit payment-status header, including grouped headers."""
    exact = _exact_column(headers, ("trang thai thanh toan", "payment status"))
    if exact is not None:
        return exact
    candidates = []
    allowed_groups = {"thanh toan", "lich su thanh toan", "payment"}
    for index, header in enumerate(headers):
        raw = str(header or "")
        if " / " not in raw:
            continue
        group, leaf = raw.rsplit(" / ", 1)
        if fold(group) in allowed_groups and fold(leaf) == "trang thai":
            candidates.append(index)
    return candidates[0] if len(candidates) == 1 else None


def _is_inventory_table(table):
    role = fold(f"{table.name} {table.source}")
    return any(term in role for term in ("the kho", "ton kho", "inventory", "stock ledger"))


def _is_purchase_table(table):
    """Identify inbound purchasing records so they cannot masquerade as sales."""
    role = fold(f"{table.name} {table.source}")
    return any(term in role for term in (
        "nhap hang", "nhaphang", "sonhaphang", "so nhap", "phieu nhap",
        "phieunhap", "nhap kho", "nhapkho",
        "purchase", "purchases", "inbound",
    ))


def _is_sales_detail_table(table):
    """Recognize explicit line-item source names for contextual header aliases."""
    role = fold(f"{table.name} {table.source}")
    return any(term in role for term in (
        "chi tiet ban hang", "so chi tiet", "donhang chitiet",
        "don hang chi tiet", "chitietbanhang", "chitietdonhang",
        "chitiethoadon", "chi tiet hoa don", "chi tiet don", "sales detail", "order detail",
    ))


def _revenue_date_column(table, allowed_headers):
    column = _exact_column(table.headers, allowed_headers)
    if column is not None:
        return column

    headers = [fold(header) for header in table.headers]
    if any(header in allowed_headers for header in ("ngay dat", "order date")):
        if "ngay dat hang" in headers:
            return headers.index("ngay dat hang")

    # Some documented sales-detail exports label the sole transaction date
    # simply "Ngày". Use it only when the source name establishes line grain
    # and no competing date column exists.
    if _is_sales_detail_table(table):
        date_columns = [index for index, header in enumerate(headers) if "ngay" in header or "date" in header]
        if len(date_columns) == 1 and headers[date_columns[0]] == "ngay":
            return date_columns[0]
    return None


def _revenue_amount_column(table):
    column = _exact_column(table.headers, LINE_AMOUNT)
    if column is not None:
        return column
    # "Tổng tiền" is a line amount only in an explicitly named detail ledger;
    # do not apply it to invoice/order summary tables.
    if _is_sales_detail_table(table):
        return _exact_column(table.headers, ("tong tien", "line total", "total amount", "trigia"))
    return None


def _is_delivery_table(table):
    role = fold(f"{table.name} {table.source}")
    return any(term in role for term in ("phieu giao", "giao hang", "delivery", "shipping"))


def _is_order_table(table):
    role = fold(f"{table.name} {table.source}")
    compact = role.replace(" ", "")
    is_order = any(marker in compact for marker in ("hoadon", "donhang", "invoice", "order"))
    is_detail = any(marker in compact for marker in (
        "chitiethoadon", "chitietdonhang", "chitietdon", "orderline", "orderlines", "orderdetail", "detail",
    ))
    return is_order and not is_detail


def _product_key_column(headers):
    for index, header in enumerate(headers):
        folded = fold(header)
        words = set(folded.split())
        if words & {"sku", "code"} or ("ma" in words and words & {"hang", "hh", "sp", "san", "pham"}):
            return index
        compact = folded.replace(" ", "")
        if compact.startswith("ma") and any(marker in compact[2:] for marker in ("hang", "hh", "sp", "sanpham")):
            return index
    return None


def _is_product_catalog_table(table):
    role = fold(f"{table.name} {table.source}").replace(" ", "")
    if any(marker in role for marker in ("chitiet", "detail", "line")):
        return False
    return any(marker in role for marker in ("sanpham", "hanghoa", "product", "item"))


def _decimal(value, decimal_separator=None):
    result = parse_decimal(value, decimal_separator=decimal_separator)
    return result.value if result.ok else None


def _column_decimal_separator(table, column):
    """Infer a numeric column policy only when its values provide decisive evidence."""
    return infer_decimal_separator(row[column] for row in table.rows if column < len(row))


def _date(value, date_system=None):
    # Vietnamese dates in the current competition data are day-first. The
    # general parser itself remains strict unless a caller supplies a policy.
    result = parse_date(value, day_first=True, excel_date_system=date_system)
    return result.value if result.ok else None


def _money(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class Executor:
    """Allowlist executor. Incomplete or ambiguous evidence returns None."""
    def __init__(
        self, tables, rules=None, *, revenue_source_shape=None,
        revenue_join_contract=None,
    ):
        self.tables = tables
        self.rules = rules or SplitRules.test_defaults()
        self.revenue_source_shape = revenue_source_shape
        self.revenue_join_contract = revenue_join_contract
        self._order_metadata_cache = {}
        self._table_date_range_cache = {}

    def _revenue_fact(self, start=None, end=None):
        if self.revenue_source_shape == "direct_line":
            candidates = self._revenue_candidates()
            return candidates[0] if len(candidates) == 1 else None
        if self.revenue_source_shape == "detail_to_order":
            joined = self._daily_revenue_fact(start, end, allow_direct=False)
        else:
            candidates = self._revenue_candidates()
            if candidates:
                return self._select_period_revenue_candidate(candidates, start, end)
            joined = self._daily_revenue_fact(start, end)
        if joined is None:
            return None
        table, date_col, value_col, status_col, _ = joined
        return table, date_col, value_col, None, status_col, _column(table.headers, ORDER)

    def _select_period_revenue_candidate(self, candidates, start, end):
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            return None
        if start is None or end is None:
            return None

        possible = []
        for candidate in candidates:
            table, date_col = candidate[0], candidate[1]
            date_range = self._table_date_range(table, date_col, candidate[4])
            if date_range is None:
                return None
            range_start, range_end = date_range
            if range_start is None or range_end is None:
                continue
            if range_start <= end and start <= range_end:
                possible.append(candidate)
        if not possible:
            return candidates[0]

        active = []
        for candidate in possible:
            table, date_col = candidate[0], candidate[1]
            rows = self._period(table, date_col, start, end, candidate[4], accepted_only=False)
            if rows is None:
                return None
            if rows:
                active.append((candidate, rows))
        if not active:
            return candidates[0]
        if len(active) == 1:
            return active[0][0]

        # Multiple sheets can be combined only when they are explicit
        # partitions of one source with identical schemas and disjoint dates.
        template = active[0][0]
        template_table, template_columns = template[0], template[1:]
        source = template_table.source
        if not source or any(
            candidate[0].source != source
            or candidate[0].headers != template_table.headers
            or candidate[0].date_system != template_table.date_system
            or candidate[1:] != template_columns
            for candidate, _ in active[1:]
        ):
            return None

        used_days, merged_rows, names = set(), [], []
        for candidate, rows in active:
            table, date_col = candidate[0], candidate[1]
            days = {_date(row[date_col], table.date_system) for row in rows}
            if None in days or used_days.intersection(days):
                return None
            used_days.update(days)
            merged_rows.extend(rows)
            names.append(table.name)

        merged = Table(
            name="+".join(names), headers=template_table.headers,
            rows=merged_rows, source=source, date_system=template_table.date_system,
        )
        return (merged, *template_columns)

    def _revenue_candidates(self):
        if not self.rules.revenue_supported:
            return []
        candidates = []
        for table in self.tables:
            if (
                _is_payment_table(table) or _is_inventory_table(table)
                or _is_purchase_table(table) or _is_delivery_table(table)
            ):
                continue
            date = _revenue_date_column(table, self.rules.revenue_date_headers)
            value = _revenue_amount_column(table)
            product = _product_column(table.headers)
            product_key = _product_key_column(table.headers)
            # A line amount must have line-level identity; order totals such as
            # `Tổng đơn` and `Phải thu` never enter this allowlist.
            if date is not None and value is not None and (product is not None or product_key is not None):
                candidates.append((table, date, value, product, _order_status_column(table.headers), _column(table.headers, ORDER)))
        return candidates

    @staticmethod
    def _join_key(value):
        if value is None or not str(value).strip():
            return None
        if isinstance(value, (int, float)):
            try:
                numeric = float(value)
                if numeric.is_integer():
                    return str(int(numeric))
            except (OverflowError, ValueError):
                pass
        return str(value).strip().casefold()

    def _daily_revenue_fact(self, start=None, end=None, *, allow_direct=True):
        """Find direct line facts or one complete, one-to-many invoice join."""
        if not self.rules.revenue_supported:
            return None
        direct = self._revenue_candidates() if allow_direct else []
        if direct:
            selected = self._select_period_revenue_candidate(direct, start, end)
            if selected is None:
                return None
            table, date_col, value_col, _, status_col, _ = selected
            return table, date_col, value_col, status_col, [table.name]

        join_contract = self.revenue_join_contract
        if join_contract is not None and tuple(join_contract.canonical_keys) != ("order_id",):
            return None

        line_candidates = []
        for table in self.tables:
            if join_contract is not None and (
                table.name, table.source
            ) != tuple(join_contract.line_table):
                continue
            if (
                _is_payment_table(table) or _is_inventory_table(table)
                or _is_purchase_table(table) or _is_delivery_table(table)
                or _is_order_table(table)
            ):
                continue
            value_col = _revenue_amount_column(table)
            line_key_col = (
                join_contract.line_key_column_index
                if join_contract is not None else _column(table.headers, ORDER)
            )
            has_item_identity = _product_column(table.headers) is not None or _product_key_column(table.headers) is not None
            if (
                value_col is not None and line_key_col is not None
                and 0 <= line_key_col < len(table.headers) and has_item_identity
            ):
                line_candidates.append((table, value_col, line_key_col))
        if len(line_candidates) != 1:
            return None

        order_candidates = []
        order_date_rule = any(
            header in {"ngay dat", "order date", "ngay tao don"}
            for header in self.rules.revenue_date_headers
        )
        for table in self.tables:
            if join_contract is not None and (
                table.name, table.source
            ) != tuple(join_contract.order_table):
                continue
            if not _is_order_table(table):
                continue
            order_key_col = (
                join_contract.order_key_column_index
                if join_contract is not None else _column(table.headers, ORDER)
            )
            if order_key_col is None or not 0 <= order_key_col < len(table.headers):
                continue
            date_choices = self.rules.revenue_date_headers
            if order_date_rule:
                # "Ngày bán" is accepted as the order date only in a table
                # whose role and unique invoice key are validated below.
                date_choices = (*date_choices, "ngay lap", "ngay ban")
            date_col = _revenue_date_column(table, date_choices)
            status_col = _order_status_column(table.headers)
            if None not in (order_key_col, date_col, status_col):
                order_candidates.append((table, order_key_col, date_col, status_col))
        if len(order_candidates) != 1:
            return None

        line_table, value_col, line_key_col = line_candidates[0]
        order_table, order_key_col, date_col, status_col = order_candidates[0]
        order_rows = {}
        for row in order_table.rows:
            if not any(value is not None and str(value).strip() for value in row):
                continue
            key = self._join_key(row[order_key_col])
            if key is None or key in order_rows:
                return None
            order_rows[key] = (row[date_col], row[status_col], row[order_key_col])
        if not order_rows:
            return None

        joined_rows, seen_line_rows = [], set()
        for row in line_table.rows:
            if not any(value is not None and str(value).strip() for value in row):
                continue
            key = self._join_key(row[line_key_col])
            if key is None or key not in order_rows:
                return None
            row_key = tuple((type(value).__name__, repr(value)) for value in row)
            if row_key in seen_line_rows:
                # An exact duplicate sale line is an export error only when
                # the active rulebook explicitly authorizes counting it once.
                # Without that policy, do not silently change the metric.
                if not self.rules.deduplicate_identical_order_lines:
                    return None
                continue
            seen_line_rows.add(row_key)
            order_date, order_status, order_id = order_rows[key]
            joined_rows.append([order_date, order_status, row[value_col], order_id])
        if not joined_rows:
            return None

        joined = Table(
            name=f"{line_table.name}+{order_table.name}",
            headers=["Ngày đặt", "Trạng thái đơn hàng", "Thành tiền", "Mã đơn"],
            rows=joined_rows,
            source=f"{line_table.source}+{order_table.source}",
            date_system=order_table.date_system,
        )
        return joined, 0, 2, 1, [line_table.name, order_table.name]

    def _joined_sales_quantity_fact(self):
        """Join one explicit sales-detail source to unique dated orders and item names."""
        detail_candidates = []
        for table in self.tables:
            if (
                not _is_sales_detail_table(table)
                or _is_payment_table(table) or _is_inventory_table(table)
                or _is_purchase_table(table) or _is_delivery_table(table)
                or _is_order_table(table)
            ):
                continue
            order_col = _column(table.headers, ORDER)
            quantity_col = _column(table.headers, QUANTITY)
            product_col = _product_column(table.headers)
            product_key_col = _product_key_column(table.headers)
            if order_col is not None and quantity_col is not None and (product_col is not None or product_key_col is not None):
                detail_candidates.append((table, order_col, quantity_col, product_col, product_key_col))
        if len(detail_candidates) != 1:
            return None

        detail, detail_order_col, quantity_col, detail_product_col, detail_product_key_col = detail_candidates[0]
        detail_rows, order_ids, product_ids = [], set(), set()
        for row in detail.rows:
            if _is_summary_row(row, detail_product_col):
                continue
            if not any(value is not None and str(value).strip() for value in row):
                continue
            order_id = self._join_key(row[detail_order_col])
            if order_id is None:
                return None
            product_key = self._join_key(row[detail_product_key_col]) if detail_product_key_col is not None else None
            if detail_product_key_col is not None and product_key is None:
                return None
            product_name = str(row[detail_product_col]).strip() if detail_product_col is not None else ""
            detail_rows.append((row, order_id, product_key, product_name))
            order_ids.add(order_id)
            if product_key is not None:
                product_ids.add(product_key)
        if not detail_rows:
            return None

        order_date_rule = any(
            header in {"ngay dat", "order date", "ngay tao don"}
            for header in self.rules.revenue_date_headers
        )
        order_date_choices = self.rules.revenue_date_headers
        if order_date_rule:
            # Competition readmes use compact NgayLap, while other sales exports
            # use Ngày bán for the same invoice-level transaction date.
            order_date_choices = (*order_date_choices, "ngay lap", "ngay ban")
        order_candidates = []
        for table in self.tables:
            if not _is_order_table(table):
                continue
            order_key_col = _column(table.headers, ORDER)
            date_col = _revenue_date_column(table, order_date_choices)
            status_col = _order_status_column(table.headers)
            if None in (order_key_col, date_col, status_col):
                continue
            order_map = {}
            valid = True
            for row in table.rows:
                if not any(value is not None and str(value).strip() for value in row):
                    continue
                order_id = self._join_key(row[order_key_col])
                if order_id is None or order_id in order_map:
                    valid = False
                    break
                order_map[order_id] = (row[date_col], row[status_col])
            if valid and order_ids.issubset(order_map):
                order_candidates.append((table, order_key_col, date_col, status_col, order_map))
        if len(order_candidates) != 1:
            return None
        order_table, _, date_col, status_col, order_map = order_candidates[0]

        product_map = None
        catalog_table = None
        if detail_product_col is None:
            catalog_candidates = []
            for table in self.tables:
                if (
                    table is detail or not _is_product_catalog_table(table)
                    or _is_payment_table(table) or _is_inventory_table(table)
                    or _is_purchase_table(table) or _is_delivery_table(table)
                    or _is_order_table(table)
                ):
                    continue
                key_col = _product_key_column(table.headers)
                name_col = _product_column(table.headers)
                if key_col is None or name_col is None:
                    continue
                mapping, valid = {}, True
                for row in table.rows:
                    if not any(value is not None and str(value).strip() for value in row):
                        continue
                    key = self._join_key(row[key_col])
                    name = str(row[name_col]).strip()
                    if key is None or not name:
                        valid = False
                        break
                    if key in mapping and fold(mapping[key]) != fold(name):
                        valid = False
                        break
                    mapping[key] = name
                if valid and product_ids.issubset(mapping):
                    catalog_candidates.append((table, mapping))
            if len(catalog_candidates) != 1:
                return None
            catalog_table, product_map = catalog_candidates[0]

        has_product_code = detail_product_key_col is not None
        headers = ["Ngày đặt", "Trạng thái đơn hàng"]
        if has_product_code:
            headers.append("Mã sản phẩm")
        product_col = len(headers)
        headers.append("Tên sản phẩm")
        value_col = len(headers)
        headers.extend(("Số lượng cơ bản", "Mã đơn"))
        order_col = len(headers) - 1
        joined_rows = []
        for row, order_id, product_key, product_name in detail_rows:
            date_value, status_value = order_map[order_id]
            if not product_name:
                product_name = product_map.get(product_key, "") if product_map is not None else ""
            if not product_name:
                return None
            joined_row = [date_value, status_value]
            if has_product_code:
                joined_row.append(product_key)
            joined_row.extend((product_name, row[quantity_col], order_id))
            joined_rows.append(joined_row)

        sources = [detail.name, order_table.name]
        if catalog_table is not None:
            sources.append(catalog_table.name)
        joined = Table(
            name="+".join(sources), headers=headers, rows=joined_rows,
            source="+".join(table.source or table.name for table in (detail, order_table, catalog_table) if table is not None),
            date_system=order_table.date_system,
        )
        return joined, 0, value_col, product_col, 1, order_col

    def _sales_quantity_fact(self):
        """Prefer one complete direct source; otherwise try the verified detail join."""
        candidates = []
        for table in self.tables:
            if _is_inventory_table(table) or _is_purchase_table(table) or _is_delivery_table(table):
                continue
            date_col = _column(table.headers, DATE)
            quantity_col = _column(table.headers, QUANTITY)
            product_col = _product_column(table.headers)
            if date_col is not None and quantity_col is not None and product_col is not None:
                candidates.append((
                    table, date_col, quantity_col, product_col,
                    _order_status_column(table.headers), _column(table.headers, ORDER),
                ))
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            return None
        return self._joined_sales_quantity_fact()

    def _quantity_unit_maps(self):
        """Read only explicit product base units and product/unit conversion ratios."""
        base_units = {}
        conversion_factors = {}
        metadata_seen = False
        for table in self.tables:
            if not _is_product_catalog_table(table):
                continue
            product_col = _product_column(table.headers)
            base_unit_col = _exact_column(table.headers, ("don vi co ban", "don vi", "don vi tinh", "base unit"))
            if product_col is None or base_unit_col is None:
                continue
            metadata_seen = True
            for row in table.rows:
                name = fold(row[product_col])
                unit = fold(row[base_unit_col])
                if not name or not unit:
                    continue
                if name in base_units and base_units[name] != unit:
                    return None
                base_units[name] = unit

        for table in self.tables:
            role = fold(f"{table.name} {table.source}").replace(" ", "")
            if not any(term in role for term in ("quydoi", "conversion")):
                continue
            product_col = _product_column(table.headers)
            unit_col = _exact_column(table.headers, ("don vi quy doi", "don vi lon", "conversion unit"))
            factor_col = _exact_column(table.headers, ("ti le quy doi", "he so quy doi", "conversion factor"))
            base_unit_col = _exact_column(table.headers, ("don vi co ban", "base unit"))
            if None in (product_col, unit_col, factor_col, base_unit_col):
                continue
            metadata_seen = True
            separator = _column_decimal_separator(table, factor_col)
            for row in table.rows:
                name, unit, base_unit = (fold(row[index]) for index in (product_col, unit_col, base_unit_col))
                factor = _decimal(row[factor_col], separator)
                if not name or not unit or not base_unit or factor is None or factor <= 0:
                    continue
                if name in base_units and base_units[name] != base_unit:
                    return None
                base_units[name] = base_unit
                key = (name, unit)
                if key in conversion_factors and conversion_factors[key] != factor:
                    return None
                conversion_factors[key] = factor
        return base_units, conversion_factors, metadata_seen

    def _base_quantity_values(self, table, rows, product_col, value_col):
        """Return quantities in the documented base unit, or fail closed."""
        separator = _column_decimal_separator(table, value_col)
        values = [_decimal(row[value_col], separator) for row in rows]
        if any(value is None for value in values):
            return None
        header = fold(table.headers[value_col]).replace(" ", "")
        base_headers = {fold(name).replace(" ", "") for name in BASE_QUANTITY}
        if header in base_headers:
            return values

        unit_col = _exact_column(table.headers, ("don vi tinh", "dvt", "unit"))
        if unit_col is None:
            return values
        maps = self._quantity_unit_maps()
        if maps is None:
            return None
        base_units, conversion_factors, metadata_seen = maps
        if not metadata_seen:
            return values
        converted = []
        for row, value in zip(rows, values):
            product_name = fold(row[product_col])
            unit = fold(row[unit_col])
            base_unit = base_units.get(product_name)
            if not product_name or not unit or not base_unit:
                return None
            if unit == base_unit:
                factor = Decimal(1)
            else:
                factor = conversion_factors.get((product_name, unit))
                if factor is None:
                    return None
            converted.append(value * factor)
        return converted

    def _fact(
        self, metric, product=False, exclude_payments=False,
        exclude_inventory=False, exclude_delivery=False, exclude_purchases=False,
    ):
        candidates = []
        for table in self.tables:
            if (exclude_payments and _is_payment_table(table)) or (exclude_inventory and _is_inventory_table(table)):
                continue
            if exclude_delivery and _is_delivery_table(table):
                continue
            if exclude_purchases and _is_purchase_table(table):
                continue
            date = _column(table.headers, DATE)
            value = _column(table.headers, metric) if metric is not None else None
            prod = _product_column(table.headers)
            if date is not None and (metric is None or value is not None) and (not product or prod is not None):
                candidates.append((table, date, value, prod, _order_status_column(table.headers), _column(table.headers, ORDER)))
        return candidates[0] if len(candidates) == 1 else None

    def _collection_fact(self):
        """Find one explicit payment-event source, using receipt time and value."""
        candidates = []
        for table in self.tables:
            if not _is_payment_table(table):
                continue
            date = _exact_column(table.headers, COLLECTION_DATE)
            if date is None:
                date = _payment_grouped_column(table.headers, {"ngay", "date"})
            value = _exact_column(table.headers, COLLECTED_AMOUNT)
            if value is None:
                value = _payment_grouped_column(table.headers, {"gia tri", "amount", "value"})
            if date is not None and value is not None:
                status = _payment_status_column(table.headers)
                if status is None:
                    # Preserve legacy single-metric behavior. The composite
                    # capability gate separately requires an exact canonical
                    # payment_status mapping before a bundle can be planned.
                    status = _column(table.headers, STATUS)
                candidates.append((table, date, value, status))
        return candidates[0] if len(candidates) == 1 else None

    def _period(self, table, date_column, start, end, status_column=None, accepted_only=True):
        matched = []
        order_column = _column(table.headers, ORDER)
        product_column = _product_column(table.headers)
        overrides = self._order_metadata_overrides(
            table, date_column, status_column, order_column, product_column,
        )
        if overrides is None:
            return None
        for index, source_row in enumerate(table.rows):
            row = source_row
            if index in overrides:
                order_id, date_value, status_value = overrides[index]
                row = list(source_row)
                row[order_column] = order_id
                row[date_column] = date_value
                if status_column is not None:
                    row[status_column] = status_value
            if _is_summary_row(row, product_column):
                continue
            if not any(value is not None and str(value).strip() for value in row):
                continue
            day = _date(row[date_column], table.date_system)
            if day is None:
                return None
            if not start <= day <= end:
                continue
            if accepted_only and status_column is not None:
                status_class = classify_order_status(row[status_column])
                if status_class in self.rules.revenue_excluded_statuses:
                    continue
                if status_class in self.rules.revenue_included_statuses or status_class == "successful":
                    pass
                elif status_class in {"pending", "in_transit"}:
                    return None
                else:
                    return None
            matched.append(row)
        return matched

    def _metadata_cache_key(self, table, date_column, status_column, order_column, product_column):
        return (id(table), date_column, status_column, order_column, product_column)

    def _order_metadata_overrides(self, table, date_column, status_column, order_column, product_column):
        if status_column is None or order_column is None or product_column is None:
            return {}
        key = self._metadata_cache_key(table, date_column, status_column, order_column, product_column)
        if key not in self._order_metadata_cache:
            self._order_metadata_cache[key] = self._fill_merged_order_metadata(
                table, date_column, status_column, order_column, product_column,
            )
        return self._order_metadata_cache[key]

    def _table_date_range(self, table, date_column, status_column):
        order_column = _column(table.headers, ORDER)
        product_column = _product_column(table.headers)
        cache_key = self._metadata_cache_key(table, date_column, status_column, order_column, product_column)
        if cache_key in self._table_date_range_cache:
            return self._table_date_range_cache[cache_key]

        overrides = self._order_metadata_overrides(
            table, date_column, status_column, order_column, product_column,
        )
        if overrides is None:
            self._table_date_range_cache[cache_key] = None
            return None

        first = last = None
        for index, source_row in enumerate(table.rows):
            row = source_row
            if _is_summary_row(row, product_column):
                continue
            if index in overrides:
                order_id, date_value, status_value = overrides[index]
                row = list(source_row)
                row[order_column] = order_id
                row[date_column] = date_value
                if status_column is not None:
                    row[status_column] = status_value
            if not any(value is not None and str(value).strip() for value in row):
                continue
            day = _date(row[date_column], table.date_system)
            if day is None:
                self._table_date_range_cache[cache_key] = None
                return None
            first = day if first is None else min(first, day)
            last = day if last is None else max(last, day)

        result = (first, last)
        self._table_date_range_cache[cache_key] = result
        return result

    def _fill_merged_order_metadata(self, table, date_column, status_column, order_column, product_column):
        """Fill blank invoice cells on line rows only within a known order group."""
        overrides = {}
        current_key = current_id = current_date = current_status = None

        def missing(value):
            return value is None or not str(value).strip() or str(value).strip().casefold() in {"none", "null", "nan"}

        def same_date(left, right):
            left_date = _date(left, table.date_system)
            right_date = _date(right, table.date_system)
            return left_date is not None and left_date == right_date

        def same_status(left, right):
            left_status, right_status = classify_order_status(left), classify_order_status(right)
            if left_status is not None and right_status is not None:
                return left_status == right_status
            return fold(left) == fold(right)

        for index, source_row in enumerate(table.rows):
            row = source_row
            nonblank = any(not missing(value) for value in row)
            if not nonblank:
                continue

            if _is_summary_row(row, product_column):
                current_key = current_id = current_date = current_status = None
                continue

            key_value = row[order_column]
            key = None if missing(key_value) else self._join_key(key_value)
            has_line_item = not missing(row[product_column])
            if key is not None:
                is_new_order = key != current_key
                if is_new_order:
                    if missing(row[date_column]) or (status_column is not None and missing(row[status_column])):
                        return None
                    current_key, current_id = key, key_value
                    current_date, current_status = row[date_column], row[status_column] if status_column is not None else None
                else:
                    if missing(row[date_column]):
                        row = list(row)
                        row[date_column] = current_date
                    elif not same_date(row[date_column], current_date):
                        return None
                    if status_column is not None:
                        if missing(row[status_column]):
                            if row is source_row:
                                row = list(row)
                            row[status_column] = current_status
                        elif not same_status(row[status_column], current_status):
                            return None
                    if row is not source_row:
                        overrides[index] = (current_id, row[date_column], current_status)
            elif has_line_item:
                if current_key is None or current_id is None or missing(current_date):
                    return None
                if not missing(row[date_column]) and not same_date(row[date_column], current_date):
                    return None
                row = list(row)
                row[order_column] = current_id
                row[date_column] = current_date
                if status_column is not None:
                    if current_status is None:
                        return None
                    if not missing(row[status_column]) and not same_status(row[status_column], current_status):
                        return None
                    row[status_column] = current_status
                overrides[index] = (current_id, current_date, current_status)
            elif not missing(row[date_column]) or (status_column is not None and not missing(row[status_column])):
                # Metadata without a product/order key cannot be safely attached.
                return None
        return overrides

    def execute(self, plan, question):
        start, end = dt.date.fromisoformat(plan.start), dt.date.fromisoformat(plan.end)
        if plan.intent == "daily_revenue_threshold_count":
            fact = self._daily_revenue_fact(start, end)
            if not fact or plan.threshold is None:
                return None
            try:
                threshold = Decimal(plan.threshold)
            except Exception:
                return None
            if not threshold.is_finite() or threshold <= 0:
                return None
            table, date_col, value_col, status_col, evidence = fact
            rows = self._period(table, date_col, start, end, status_col)
            if rows is None or not rows:
                return None
            decimal_separator = _column_decimal_separator(table, value_col)
            daily_totals = {}
            for row in rows:
                day = _date(row[date_col], table.date_system)
                value = _decimal(row[value_col], decimal_separator)
                if day is None or value is None:
                    return None
                daily_totals[day] = daily_totals.get(day, Decimal(0)) + value
            answer = sum(total >= threshold for total in daily_totals.values())
            return {"type": "number", "answer": answer, "evidence": evidence}
        if plan.intent == "order_revenue_threshold_count":
            fact = self._revenue_fact(start, end)
            if not fact or plan.threshold is None:
                return None
            try:
                threshold = Decimal(plan.threshold)
            except Exception:
                return None
            if not threshold.is_finite() or threshold <= 0:
                return None
            table, date_col, value_col, _, status_col, order_col = fact
            if order_col is None:
                return None
            rows = self._period(table, date_col, start, end, accepted_only=False)
            if rows is None or not rows:
                return None
            orders = {}
            for row in rows:
                key = self._join_key(row[order_col])
                if key is None:
                    return None
                status_class = classify_order_status(row[status_col]) if status_col is not None else None
                order = orders.setdefault(key, {"status": status_class, "amounts": []})
                if status_col is not None and (status_class is None or order["status"] != status_class):
                    return None
                order["amounts"].append(row[value_col])

            decimal_separator = _column_decimal_separator(table, value_col)
            count = 0
            eligible_count = 0
            eligible = set(self.rules.revenue_included_statuses) | {"successful"}
            for order in orders.values():
                if status_col is not None:
                    if order["status"] in self.rules.revenue_excluded_statuses:
                        continue
                    if order["status"] not in eligible:
                        return None
                amounts = [_decimal(value, decimal_separator) for value in order["amounts"]]
                if any(value is None for value in amounts):
                    return None
                eligible_count += 1
                count += int(sum(amounts, Decimal(0)) >= threshold)
            if not eligible_count:
                return None
            return {"type": "number", "answer": count, "evidence": [table.name]}
        if plan.intent in ("revenue", "collected_amount", "quantity"):
            if plan.intent == "collected_amount":
                fact = self._collection_fact()
            elif plan.intent == "revenue":
                fact = self._revenue_fact(start, end)
            else:
                fact = self._fact(
                    QUANTITY,
                    exclude_purchases=True,
                )
            if not fact:
                return None
            if plan.intent == "collected_amount":
                table, date_col, value_col, status_col = fact
                product_col = None
            else:
                table, date_col, value_col, product_col, status_col, _ = fact
            rows = self._period(
                table, date_col, start, end, status_col,
                accepted_only=plan.intent != "collected_amount",
            )
            if rows is None or not rows:
                return None
            if plan.intent == "collected_amount" and status_col is not None:
                settled = []
                nonsettled = {"cancelled", "returned", "delivery_failed", "pending", "in_transit"}
                for row in rows:
                    status_class = classify_payment_status(row[status_col])
                    if status_class == "successful":
                        settled.append(row)
                    elif status_class in nonsettled or status_class in {
                        "failed", "refunded", "reversed",
                    }:
                        continue
                    else:
                        return None
                rows = settled
                if not rows:
                    return None
            if product_col is not None:
                qwords = tokens(question)
                names = sorted({str(r[product_col]).strip() for r in rows if str(r[product_col]).strip()}, key=len, reverse=True)
                target = next((x for x in names if len(tokens(x)) > 1 and tokens(x).issubset(qwords)), None)
                if target:
                    rows = [r for r in rows if str(r[product_col]).strip() == target]
            decimal_separator = _column_decimal_separator(table, value_col)
            values = [_decimal(row[value_col], decimal_separator) for row in rows]
            if any(value is None for value in values):
                return None
            total = sum(values, Decimal(0))
            answer = _money(total) if plan.intent == "revenue" else float(total.quantize(Decimal("0.01")))
            return {"type": "number", "answer": int(answer) if isinstance(answer, float) and answer.is_integer() else answer, "evidence": [table.name]}
        if plan.intent == "order_count":
            fact = self._fact(None, exclude_payments=True, exclude_delivery=True, exclude_purchases=True)
            if fact is None:
                revenue_fact = self._revenue_fact(start, end)
                if revenue_fact is not None and revenue_fact[5] is not None:
                    table, date_col, _, _, status_col, order_col = revenue_fact
                    fact = (table, date_col, None, None, status_col, order_col)
            if not fact or fact[5] is None:
                return None
            table, date_col, _, _, status_col, order_col = fact
            rows = self._period(table, date_col, start, end, status_col)
            if rows is None or not rows:
                return None
            ids = {str(r[order_col]).strip() for r in rows}
            if "" in ids:
                return None
            return {"type": "number", "answer": len(ids), "evidence": [table.name]}
        if plan.intent == "cancellation_rate":
            options = []
            for table in self.tables:
                if _is_payment_table(table):
                    continue
                date_col, status_col, order_col = _column(table.headers, DATE), _order_status_column(table.headers), _column(table.headers, ORDER)
                if None not in (date_col, status_col, order_col):
                    options.append((table, date_col, status_col, order_col))
            if not options:
                return None
            if len(options) != 1:
                return None
            table, date_col, status_col, order_col = options[0]
            rows = self._period(table, date_col, start, end, accepted_only=False)
            if rows is None or not rows:
                return None
            orders = {}
            for row in rows:
                order_id, status = str(row[order_col]).strip(), row[status_col]
                if not order_id or order_id.casefold() in {"none", "null", "nan"}:
                    return None
                status_class = classify_order_status(status)
                if status_class is None:
                    return None
                if order_id in orders and orders[order_id] != status_class:
                    return None
                orders[order_id] = status_class
            rate = Decimal(sum(v in self.rules.cancellation_numerator_statuses for v in orders.values())) * 100 / len(orders)
            return {"type": "percent", "answer": float(rate.quantize(Decimal("0.01"))), "evidence": [table.name]}
        if plan.intent == "sales_ranking":
            q = fold(question)
            explicit_revenue = any(term in q for term in (
                "doanh thu", "doanh so", "tien ban", "nhieu tien", "gia tri", "amount", "revenue",
            ))
            explicit_quantity = any(term in q for term in (
                "so luong", "ban chay", "ban nhieu", "hot nhat", "quantity",
            ))
            rank_metric = "revenue" if explicit_revenue else "quantity" if explicit_quantity else self.rules.ranking_default
            if rank_metric == "revenue":
                fact = self._revenue_fact()
            elif rank_metric == "quantity":
                fact = self._sales_quantity_fact()
            else:
                fact = None
            if not fact:
                return None
            table, date_col, value_col, product_col, status_col, _ = fact
            product_key_col = _product_key_column(table.headers)
            if self.rules.tie_breaker == "code" and product_key_col is None:
                return None
            totals, display_names = {}, {}
            rows = self._period(table, date_col, start, end, status_col)
            if rows is None or not rows:
                return None
            base_quantities = (
                self._base_quantity_values(table, rows, product_col, value_col)
                if rank_metric == "quantity" else None
            )
            if rank_metric == "quantity" and base_quantities is None:
                return None
            decimal_separator = _column_decimal_separator(table, value_col)
            for index, row in enumerate(rows):
                name = str(row[product_col]).strip() if product_col is not None else ""
                code = str(row[product_key_col]).strip() if product_key_col is not None else ""
                value = base_quantities[index] if base_quantities is not None else _decimal(row[value_col], decimal_separator)
                if (not name and not code) or (product_key_col is not None and not code) or value is None:
                    return None
                if name and fold(name) != "phi phuc vu":
                    key = code if product_key_col is not None else name
                    totals[key] = totals.get(key, Decimal(0)) + value
                    display_names.setdefault(key, name or code)
            if not totals:
                return None
            def tie_key(key):
                if self.rules.tie_breaker in ("code", "code_or_name") and product_key_col is not None:
                    return fold(key)
                return fold(display_names[key])
            ranked = sorted(totals, key=lambda key: (-totals[key], tie_key(key)))[:plan.top_k]
            names = [display_names[key] for key in ranked]
            return {"type": "string", "answer": names[0], "evidence": [table.name]} if plan.top_k == 1 else {"type": "list", "answer": names, "evidence": [table.name]}
        return None

    def _customer_group_revenue_share(self, plan):
        try:
            filters = dict(plan.filters)
        except (TypeError, ValueError):
            return None, "unresolved_filter"
        candidate, reason = execute_customer_group_revenue_share(
            self.tables,
            self.rules,
            plan.start,
            plan.end,
            filters.get("customer_group"),
        )
        reason_codes = {
            "unresolved_filter": "ambiguous_entity",
            "temporal_scope_not_executable": "missing_time_range",
            "source_scope_mismatch": "join_unsafe",
            "missing_required_fields": "missing_column",
            "relationship_not_validated": "join_unsafe",
            "join_contract_invalid": "join_unsafe",
            "join_execution_failed": "join_unsafe",
            "join_result_incomplete": "insufficient_evidence",
            "malformed_fact_row": "parse_failure",
            "invalid_order_date": "parse_failure",
            "unverified_order_status": "unknown_order_status",
            "invalid_revenue_amount": "parse_failure",
            "no_eligible_revenue": "no_data",
        }
        return candidate, reason_codes.get(reason, reason)

    def _customer_group_revenue_total(self, plan):
        try:
            filters = dict(plan.filters)
        except (TypeError, ValueError):
            return None, "ambiguous_entity"
        candidate, reason = execute_customer_group_revenue_total(
            self.tables, self.rules, plan.start, plan.end,
            filters.get("customer_group"),
        )
        reason_codes = {
            "unresolved_filter": "ambiguous_entity",
            "temporal_scope_not_executable": "missing_time_range",
            "source_scope_mismatch": "join_unsafe",
            "missing_required_fields": "missing_column",
            "relationship_not_validated": "join_unsafe",
            "join_contract_invalid": "join_unsafe",
            "join_execution_failed": "join_unsafe",
            "join_result_incomplete": "insufficient_evidence",
            "malformed_fact_row": "parse_failure",
            "invalid_order_date": "parse_failure",
            "unverified_order_status": "unknown_order_status",
            "invalid_revenue_amount": "parse_failure",
            "no_eligible_revenue": "no_data",
        }
        return candidate, reason_codes.get(reason, reason)

    def execute_with_reason(self, plan, question, *, spec=None):
        """Run the allowlisted executor and return an internal abstention reason."""
        if plan is None:
            return None, "unsupported_intent"
        if plan.intent == "customer_group_revenue_share":
            if spec is None or spec.business_id != "biz_129":
                return None, "unsupported_intent"
            if spec.unit != "percent":
                return None, "invalid_unit"
            return self._customer_group_revenue_share(plan)
        if plan.intent == "customer_group_revenue_total":
            if spec is None or spec.business_id != "biz_129":
                return None, "unsupported_intent"
            if fold(spec.unit) != "vnd":
                return None, "invalid_unit"
            return self._customer_group_revenue_total(plan)
        if plan.intent in {"revenue", "order_revenue_threshold_count"} and not self.rules.revenue_supported:
            return None, "rulebook_unavailable"
        if spec is not None and spec.unit and plan.intent in ("revenue", "collected_amount", "order_revenue_threshold_count") and fold(spec.unit) != "vnd":
            return None, "invalid_unit"
        if spec is not None and spec.unit and plan.intent in ("quantity", "sales_ranking"):
            metric = QUANTITY
            fact = self._fact(
                metric,
                product=plan.intent == "sales_ranking",
                exclude_inventory=plan.intent == "sales_ranking",
                exclude_purchases=True,
            )
            if fact:
                table, date_col, _, _, status_col, _ = fact
                unit_column = _column(table.headers, ("don vi tinh", "dvt", "unit"))
                if unit_column is None:
                    return None, "invalid_unit"
                rows = self._period(
                    table, date_col, dt.date.fromisoformat(plan.start),
                    dt.date.fromisoformat(plan.end), status_col,
                )
                wanted = fold(spec.unit)
                if rows is not None and rows and any(fold(row[unit_column]) != wanted for row in rows):
                    return None, "invalid_unit"

        candidate = self.execute(plan, question)
        if candidate is not None:
            return candidate, None
        return None, self._failure_reason(plan)

    def _failure_reason(self, plan):
        intent = plan.intent
        if intent in ("revenue", "order_revenue_threshold_count"):
            if not self.rules.revenue_supported:
                return "rulebook_unavailable"
            revenue_fact = self._revenue_fact(
                dt.date.fromisoformat(plan.start), dt.date.fromisoformat(plan.end),
            )
            if not revenue_fact:
                return "missing_column"
            table, date_col, *_ = revenue_fact
            return "no_data" if self._no_data_in_period(plan, table, date_col) else "insufficient_evidence"
        if intent == "quantity":
            metric = QUANTITY
            candidates = []
            for table in self.tables:
                date_col, value_col = _column(table.headers, DATE), _column(table.headers, metric)
                if date_col is not None and value_col is not None:
                    candidates.append((table, date_col))
            if not candidates:
                return "missing_column"
            if len(candidates) == 1 and self._no_data_in_period(plan, *candidates[0]):
                return "no_data"
            return "insufficient_evidence"
        if intent in {"daily_revenue_threshold_count", "order_revenue_threshold_count"}:
            if not self.rules.revenue_supported:
                return "rulebook_unavailable"
            if intent == "daily_revenue_threshold_count":
                fact = self._daily_revenue_fact(
                    dt.date.fromisoformat(plan.start), dt.date.fromisoformat(plan.end),
                )
            else:
                fact = self._revenue_fact(
                    dt.date.fromisoformat(plan.start), dt.date.fromisoformat(plan.end),
                )
            if not fact:
                return "missing_column"
            table, date_col, *_ = fact
            return "no_data" if self._no_data_in_period(plan, table, date_col) else "insufficient_evidence"
        if intent == "collected_amount":
            candidates = [
                (table, _exact_column(table.headers, COLLECTION_DATE)) for table in self.tables
                if _is_payment_table(table)
                and _exact_column(table.headers, COLLECTION_DATE) is not None
                and _exact_column(table.headers, COLLECTED_AMOUNT) is not None
            ]
            if not candidates:
                return "missing_column"
            if len(candidates) == 1 and self._no_data_in_period(plan, *candidates[0]):
                return "no_data"
            return "insufficient_evidence"
        if intent == "order_count":
            candidates = [
                (table, _column(table.headers, DATE)) for table in self.tables
                if not _is_payment_table(table) and not _is_delivery_table(table) and not _is_purchase_table(table)
                and _column(table.headers, DATE) is not None
                and _column(table.headers, ORDER) is not None
            ]
            if not candidates:
                return "missing_column"
            if len(candidates) == 1 and self._no_data_in_period(plan, *candidates[0]):
                return "no_data"
            return "insufficient_evidence"
        if intent == "cancellation_rate":
            return self._cancellation_rate_failure_reason(plan)
        if intent == "sales_ranking":
            candidates = [
                (table, _column(table.headers, DATE)) for table in self.tables
                if not _is_inventory_table(table) and not _is_purchase_table(table)
                and _column(table.headers, DATE) is not None
                and _column(table.headers, QUANTITY) is not None
            ]
            if not candidates:
                return "missing_column"
            product_candidates = [
                (table, date_col) for table, date_col in candidates
                if _product_column(table.headers) is not None
            ]
            if len(product_candidates) == 1 and self._no_data_in_period(plan, *product_candidates[0]):
                return "no_data"
            if not product_candidates:
                if any(_product_key_column(table.headers) is not None for table, _ in candidates):
                    return "join_unsafe"
                return "join_unsafe" if any(_is_inventory_table(table) for table in self.tables) else "missing_column"
            return "insufficient_evidence"
        return "insufficient_evidence"

    def _no_data_in_period(self, plan, table, date_column):
        rows = self._period(
            table, date_column, dt.date.fromisoformat(plan.start),
            dt.date.fromisoformat(plan.end), accepted_only=False,
        )
        return rows == []

    def _cancellation_rate_failure_reason(self, plan):
        candidates = []
        for table in self.tables:
            if _is_payment_table(table) or _is_purchase_table(table):
                continue
            date_col = _column(table.headers, DATE)
            status_col = _order_status_column(table.headers)
            order_col = _column(table.headers, ORDER)
            if None not in (date_col, status_col, order_col):
                candidates.append((table, date_col, status_col, order_col))
        if not candidates:
            return "missing_column"
        if len(candidates) != 1:
            return "insufficient_evidence"

        table, date_col, status_col, order_col = candidates[0]
        rows = self._period(
            table, date_col, dt.date.fromisoformat(plan.start),
            dt.date.fromisoformat(plan.end), accepted_only=False,
        )
        if rows is None:
            return "insufficient_evidence"
        if not rows:
            return "no_data"

        order_statuses = {}
        missing_status = unknown_status = conflicting_status = False
        for row in rows:
            status = row[status_col]
            status_class = classify_order_status(status)
            if status_class is None:
                if status is None or not str(status).strip():
                    missing_status = True
                else:
                    unknown_status = True
                continue
            order_id = str(row[order_col]).strip()
            if not order_id or order_id.casefold() in {"none", "null", "nan"}:
                continue
            if order_id in order_statuses and order_statuses[order_id] != status_class:
                conflicting_status = True
            order_statuses[order_id] = status_class

        if missing_status:
            return "missing_order_status"
        if unknown_status:
            return "unknown_order_status"
        if conflicting_status:
            return "conflicting_order_status"
        return "insufficient_evidence"
