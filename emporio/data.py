"""Load and clean the CSV data into typed in-memory objects.

Cleaning decisions (see README "Data handling"):
* numbers/dates are parsed, ``specs`` JSON is parsed, whitespace is stripped;
* a product's *availability* is derived from ``status`` AND ``stock_quantity`` — a
  discontinued or "coming soon" item is never sellable even if stock > 0;
* only promotions with ``is_active = 1`` count;
* order totals are kept as recorded; inconsistencies are reported by ``quality_report``.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import DATA_DIR

BRANDS = (
    "Yamaha", "Tagima", "Giannini", "Rozini", "Shelby", "Crafter", "Martin", "Taylor", "Takamine",
    "Kala", "Ohana", "Kalani", "Fender", "Gibson", "Ibanez", "PRS", "Music Man", "Korg", "Nord",
    "Roland", "Pearl",
)


@dataclass(frozen=True)
class Promotion:
    id: int
    product_id: int
    percent: float
    label: str
    active: bool


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    brand: str
    price: float
    category_id: int
    category: str
    description: str
    stock: int
    status: str  # active | discontinued | coming_soon
    specs: dict
    created_at: date

    @property
    def availability(self) -> str:
        if self.status == "discontinued":
            return "discontinued"
        if self.status == "coming_soon":
            return "coming_soon"
        return "available" if self.stock > 0 else "out_of_stock"

    @property
    def sellable(self) -> bool:
        return self.availability == "available"


@dataclass(frozen=True)
class Customer:
    id: int
    name: str
    phone: str
    email: str
    city: str


@dataclass(frozen=True)
class OrderItem:
    product_id: int
    quantity: int


@dataclass(frozen=True)
class Order:
    id: int
    customer_id: int
    date: date
    status: str  # pending | confirmed | shipped | delivered | cancelled
    total: float
    payment_method: str
    tracking_code: str
    estimated_delivery: date | None
    notes: str
    items: tuple[OrderItem, ...] = ()


@dataclass
class Store:
    categories: dict[int, str]
    products: dict[int, Product]
    customers: dict[int, Customer]
    orders: dict[int, Order]
    promotions: list[Promotion] = field(default_factory=list)

    def active_promotion(self, product_id: int) -> Promotion | None:
        found = [p for p in self.promotions if p.product_id == product_id and p.active]
        return max(found, key=lambda p: p.percent) if found else None


def _rows(data_dir: Path, name: str) -> list[dict[str, str]]:
    with open(data_dir / f"{name}.csv", encoding="utf-8-sig", newline="") as fh:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def _date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _brand(name: str) -> str:
    return next((b for b in BRANDS if b.lower() in name.lower()), "")


def load_store(data_dir: Path = DATA_DIR) -> Store:
    categories = {int(r["category_id"]): r["name"] for r in _rows(data_dir, "categories")}

    products = {}
    for r in _rows(data_dir, "products"):
        try:
            specs = json.loads(r["specs"]) if r["specs"] else {}
        except json.JSONDecodeError:
            specs = {}
        p = Product(
            id=int(r["product_id"]), name=r["name"], brand=_brand(r["name"]),
            price=float(r["price_brl"]), category_id=int(r["category_id"]),
            category=categories.get(int(r["category_id"]), "Outros"), description=r["description"],
            stock=max(int(r["stock_quantity"] or 0), 0), status=r["status"].lower(), specs=specs,
            created_at=date.fromisoformat(r["created_at"]),
        )
        products[p.id] = p

    customers = {
        int(r["customer_id"]): Customer(int(r["customer_id"]), r["name"], r["phone"], r["email"].lower(), r["city"])
        for r in _rows(data_dir, "customers")
    }

    items: dict[int, list[OrderItem]] = {}
    for r in _rows(data_dir, "order_items"):
        items.setdefault(int(r["order_id"]), []).append(OrderItem(int(r["product_id"]), int(r["quantity"])))

    orders = {}
    for r in _rows(data_dir, "orders"):
        oid = int(r["order_id"])
        orders[oid] = Order(
            id=oid, customer_id=int(r["customer_id"]), date=date.fromisoformat(r["order_date"]),
            status=r["status"].lower(), total=float(r["total_brl"]), payment_method=r["payment_method"].lower(),
            tracking_code=r["tracking_code"], estimated_delivery=_date(r["estimated_delivery"]),
            notes=r["notes"], items=tuple(items.get(oid, [])),
        )

    promotions = [
        Promotion(int(r["promotion_id"]), int(r["product_id"]), float(r["discount_percent"]),
                  r["description"], r["is_active"] == "1")
        for r in _rows(data_dir, "promotions")
    ]
    return Store(categories, products, customers, orders, promotions)


def quality_report(store: Store) -> list[str]:
    """Human-readable list of data inconsistencies found (documented in the README)."""
    out = []
    for p in store.products.values():
        if p.status == "active" and p.stock == 0:
            out.append(f"Product {p.id} '{p.name}' is active but has zero stock -> treated as out_of_stock.")
        if p.status in ("discontinued", "coming_soon") and p.stock > 0:
            out.append(f"Product {p.id} '{p.name}' is {p.status} but shows stock {p.stock} -> never sellable.")
    used = {p.category_id for p in store.products.values()}
    for cid, name in store.categories.items():
        if cid not in used:
            out.append(f"Category {cid} '{name}' has no products (the manual claims the store sells them).")
    for o in store.orders.values():
        expected = sum(store.products[i.product_id].price * i.quantity for i in o.items)
        if o.items and abs(expected - o.total) > 0.01:
            out.append(f"Order {o.id}: recorded total {o.total} != items at current prices {expected:.2f} "
                       f"-> recorded total is used.")
    emails: dict[str, list[int]] = {}
    for c in store.customers.values():
        emails.setdefault(c.email, []).append(c.id)
    for email, ids in emails.items():
        if len(ids) > 1:
            out.append(f"E-mail {email} is shared by customers {ids} -> identity checks must match order + contact.")
    return out
