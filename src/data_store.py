"""Read-only data-room loader with normalisation and indexes."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .normalise import normalise_email, parse_date, parse_datetime, parse_money


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    email: str


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_id: str
    order_date: Any
    status: str
    order_total: Decimal
    shipping_fee: Decimal


@dataclass(frozen=True)
class OrderItem:
    order_id: str
    line_no: int
    sku: str
    product_name: str
    qty: int
    unit_price: Decimal


@dataclass(frozen=True)
class Shipment:
    shipment_id: str
    order_id: str
    carrier: str
    tracking_no: str
    status: str
    shipped_at: Any
    delivered_at: Any
    last_event_at: Any


@dataclass(frozen=True)
class Refund:
    refund_id: str
    order_id: str
    line_no: int
    amount: Decimal
    status: str
    requested_at: Any
    approved_by: str


@dataclass
class DataStore:
    data_dir: Path
    customers_by_id: dict[str, Customer] = field(default_factory=dict)
    customers_by_email: dict[str, Customer] = field(default_factory=dict)
    orders_by_id: dict[str, Order] = field(default_factory=dict)
    items_by_order: dict[str, list[OrderItem]] = field(default_factory=dict)
    shipments_by_order: dict[str, Shipment] = field(default_factory=dict)
    refunds_by_order_line: dict[tuple[str, int], list[Refund]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, data_dir: str | Path | None = None) -> "DataStore":
        root = Path(data_dir) if data_dir else Path(__file__).resolve().parent.parent / "data"
        store = cls(data_dir=root)
        store._load_customers()
        store._load_orders()
        store._load_items()
        store._load_shipments()
        store._load_refunds()
        return store

    def _rows(self, name: str) -> list[dict[str, str]]:
        with (self.data_dir / name).open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def _load_customers(self) -> None:
        rows = self._rows("customers.csv")
        self.counts["customers"] = len(rows)
        for row in rows:
            customer = Customer(
                customer_id=row["customer_id"].strip(),
                name=row["name"].strip(),
                email=row["email"].strip(),
            )
            self.customers_by_id[customer.customer_id] = customer
            self.customers_by_email[normalise_email(customer.email)] = customer

    def _load_orders(self) -> None:
        rows = self._rows("orders.csv")
        self.counts["order_rows"] = len(rows)
        for row in rows:
            order_id = row["order_id"].strip()
            if order_id in self.orders_by_id:
                self.counts["duplicate_order_rows"] = self.counts.get("duplicate_order_rows", 0) + 1
                continue
            self.orders_by_id[order_id] = Order(
                order_id=order_id,
                customer_id=row["customer_id"].strip(),
                order_date=parse_date(row["order_date"]),
                status=row["status"].strip(),
                order_total=parse_money(row["Order Total"]),
                shipping_fee=parse_money(row["shipping_fee"]),
            )
        self.counts["unique_orders"] = len(self.orders_by_id)

    def _load_items(self) -> None:
        rows = self._rows("order_items.csv")
        self.counts["order_items"] = len(rows)
        orphans = 0
        for row in rows:
            order_id = row["order_id"].strip()
            if order_id not in self.orders_by_id:
                orphans += 1
                continue
            item = OrderItem(
                order_id=order_id,
                line_no=int(row["line_no"]),
                sku=row["sku"].strip(),
                product_name=row["product_name"].strip(),
                qty=int(row["qty"]),
                unit_price=parse_money(row["unit_price"]),
            )
            self.items_by_order.setdefault(order_id, []).append(item)
        for items in self.items_by_order.values():
            items.sort(key=lambda item: item.line_no)
        self.counts["item_orphans"] = orphans

    def _load_shipments(self) -> None:
        rows = self._rows("shipments.csv")
        self.counts["shipments"] = len(rows)
        for row in rows:
            order_id = row["order_id"].strip()
            self.shipments_by_order[order_id] = Shipment(
                shipment_id=row["shipment_id"].strip(),
                order_id=order_id,
                carrier=row["carrier"].strip(),
                tracking_no=row["tracking_no"].strip(),
                status=row["status"].strip(),
                shipped_at=parse_datetime(row["shipped_at"]),
                delivered_at=parse_datetime(row["delivered_at"]),
                last_event_at=parse_datetime(row["last_event_at"]),
            )

    def _load_refunds(self) -> None:
        rows = self._rows("refunds.csv")
        self.counts["refunds"] = len(rows)
        for row in rows:
            refund = Refund(
                refund_id=row["refund_id"].strip(),
                order_id=row["order_id"].strip(),
                line_no=int(row["line_no"]),
                amount=parse_money(row["amount"]),
                status=row["status"].strip(),
                requested_at=parse_datetime(row["requested_at"]),
                approved_by=row["approved_by"].strip(),
            )
            self.refunds_by_order_line.setdefault((refund.order_id, refund.line_no), []).append(refund)

    def items_for(self, order_id: str | None) -> list[OrderItem]:
        return self.items_by_order.get(order_id or "", [])

    def shipment_for(self, order_id: str | None) -> Shipment | None:
        return self.shipments_by_order.get(order_id or "")

    def customer_for(self, order: Order | None) -> Customer | None:
        if not order:
            return None
        return self.customers_by_id.get(order.customer_id)

    def refunds_for(self, order_id: str, line_no: int) -> list[Refund]:
        return self.refunds_by_order_line.get((order_id, line_no), [])
