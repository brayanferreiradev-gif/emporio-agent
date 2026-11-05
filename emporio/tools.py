"""Tools exposed to the LLM (function calling).

Design rules:
* Tools return small JSON-able dicts with money/dates ALREADY formatted — the model never does arithmetic.
* Anything about a customer's order requires order number + contact (e-mail or phone) that match.
* Docstrings are the tool descriptions the model sees, so they say *when* to call each tool.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Callable

from . import catalog, config, rules
from .data import Order, Product, Store
from .policies import PolicyIndex
from .session import MAX_FAILED_VERIFICATIONS, Session
from .text import brl, normalize

STATUS_PT = {
    "pending": "Aguardando confirmação do pagamento",
    "confirmed": "Pagamento confirmado — pedido em preparação",
    "shipped": "Enviado — a caminho do cliente",
    "delivered": "Entregue",
    "cancelled": "Cancelado",
}
PAYMENT_PT = {"pix": "PIX", "debit": "Cartão de débito", "boleto": "Boleto bancário"}
ACCESSORY_RE = re.compile(r"\b(cordas?|palhetas?|cabos?|pedais|pedal|amplificador(es)?|cases?|capas?|afinador(es)?)\b")
LARGE_ITEM_RE = re.compile(r"bateria ac[uú]stica|piano|contrabaixo ac", re.I)


def _payment_label(code: str) -> str:
    m = re.fullmatch(r"credit_(\d+)x", code)
    return f"Cartão de crédito em {m.group(1)}x" if m else PAYMENT_PT.get(code, code)


def _digits(s: str) -> str:
    d = re.sub(r"\D", "", s)
    return d[2:] if d.startswith("55") and len(d) > 11 else d


class Tools:
    def __init__(self, store: Store, policies: PolicyIndex, session: Session,
                 clock: Callable[[], datetime] = config.now, var_dir=config.VAR_DIR):
        self.store, self.policies, self.session, self.clock, self.var_dir = store, policies, session, clock, var_dir
        self.trace: list[dict] = []  # tool calls of the current turn (for --verbose / example logs)

    # the callables handed to the model (their docstrings become the tool descriptions)
    def as_functions(self) -> list[Callable]:
        return [
            self.search_products, self.get_product_details, self.get_payment_options, self.get_shipping_info,
            self.get_store_info, self.search_policies, self.get_order_status, self.check_return_eligibility,
            self.escalate_to_human,
        ]

    # ------------------------------------------------------------------ catalogue
    def _view(self, p: Product, detailed: bool = False) -> dict:
        v = {"product_id": p.id, "name": p.name, "category": p.category, "availability": p.availability,
             **rules.price_info(self.store, p)}
        v.pop("price_value", None)
        if p.availability == "available":
            v["units_in_stock"] = p.stock
        if detailed:
            v["description"], v["specs"] = p.description, p.specs
        if not p.sellable:
            v["alternatives"] = [self._view(a) for a in catalog.alternatives(self.store, p, 2)]
        return v

    def search_products(self, query: str = "", category: str = "", brand: str = "",
                        min_price: float = 0, max_price: float = 0) -> dict:
        """Search the product catalogue (live prices, promotions and stock). Call this for ANY question about
        which instruments exist, prices, availability, options in a budget, or a specific model.

        Args:
            query: free-text keywords in Portuguese, e.g. "aço folk", "Takamine GD20", "soprano". May be empty
                when only filtering by category/price.
            category: instrument family, e.g. "Violões", "Guitarras", "Baixos", "Baterias e Percussão",
                "Teclados e Pianos", "Ukuleles", "Sopro", "Cordas Orquestrais".
            brand: brand filter, e.g. "Yamaha".
            min_price: minimum price in BRL (0 = no minimum).
            max_price: maximum price in BRL the customer would pay, promotions included (0 = no maximum).
        """
        found = catalog.search(self.store, query, category, brand, min_price or None, max_price or None)
        sellable = [p for p, _ in found if p.sellable]
        unavailable = [p for p, _ in found if not p.sellable]
        out: dict = {"total_available_matches": len(sellable), "results": [self._view(p) for p in sellable[:8]]}
        if len(sellable) > 8:
            out["note"] = f"Showing 8 of {len(sellable)}; ask the customer to narrow down (type, budget, brand)."
        # Named product that cannot be sold: surface it (manual §7.3: never confirm what is not in stock).
        if unavailable and query:
            out["matches_not_for_sale"] = [self._view(p) for p in unavailable[:3]]
        if category:
            ids = catalog.resolve_categories(self.store, category)
            if ids and not any(p.category_id in ids for p in self.store.products.values()):
                out["note"] = "The catalogue currently has NO products in this category."
        if ACCESSORY_RE.search(normalize(query)) and not re.search(r"\b\d\s*cordas\b", normalize(query)):
            out["scope_warning"] = ("Query looks like an ACCESSORY (strings, picks, cables, pedals, amps, cases). "
                                    "The store sells instruments only — do not present these results as accessories.")
        if not sellable and not unavailable:
            out["note"] = out.get("note", "No product matched.")
        return out

    def get_product_details(self, product_id: int) -> dict:
        """Full details (price, promotion, stock, specs, description) of ONE product by its id, as returned by
        search_products. Use it when the customer asks about a specific model after a search."""
        p = self.store.products.get(int(product_id))
        return self._view(p, detailed=True) if p else {"error": f"Product {product_id} not found."}

    def get_payment_options(self, product_id: int, quantity: int = 1) -> dict:
        """Payment methods for a product: PIX price, card installments, debit, boleto. Call this when the customer
        asks how to pay, about instalments (parcelas), PIX discount or 'how much per month'. Applies the store's
        rules (PIX 5% discount only on non-promotional prices, minimum instalment values)."""
        p = self.store.products.get(int(product_id))
        if not p:
            return {"error": f"Product {product_id} not found."}
        if not p.sellable:
            return {"error": f"'{p.name}' is {p.availability}; cannot be sold now.", "alternatives": self._view(p)["alternatives"]}
        return rules.payment_options(self.store, p, max(int(quantity), 1))

    # ------------------------------------------------------------------ store info & policies
    def get_shipping_info(self, city: str = "", order_value: float = 0) -> dict:
        """Delivery fee and deadline. Call when the customer asks about frete/entrega/prazo. Pass the customer's
        city if known and the order value in BRL (0 if unknown). Free shipping and the flat fee depend on both."""
        return rules.shipping_info(city or None, order_value or None)

    def get_store_info(self) -> dict:
        """Address, phone/WhatsApp, e-mail, opening hours AND whether the store is open right now (with the next
        opening time). Call this for hours, 'are you open?', location or contact questions."""
        return {**rules.STORE_INFO, **rules.store_status(self.clock())}

    def search_policies(self, question: str) -> dict:
        """Look up the store's official policy manual: returns/refunds/exchanges, warranty, payment rules,
        shipping rules, promotions rules, privacy (LGPD), what to do with complaints, scope of the store.
        Call this BEFORE answering any 'what is the rule/policy/can I...' question. Write `question` in Portuguese."""
        hits = self.policies.search(question, k=3)
        if not hits:
            return {"found": False, "note": "No relevant policy found. Do not invent one — offer a hand-off to the team."}
        return {"found": True, "internal_document": True,
                "sections": [{"section": s.ref, "title": s.title, "text": s.text} for s, _ in hits]}

    # ------------------------------------------------------------------ orders (identity required)
    def _authorize(self, order_id: int, contact: str) -> tuple[Order | None, dict | None]:
        if self.session.failed_verifications >= MAX_FAILED_VERIFICATIONS:
            return None, {"error": "Too many failed verification attempts in this chat. Do not retry; "
                                   "offer escalate_to_human so the team can verify the customer."}
        try:
            order = self.store.orders.get(int(order_id))
        except (TypeError, ValueError):
            order = None
        if order and order.date > self.clock().date():
            order = None  # order "from the future" relative to the simulated clock
        customer = self.store.customers.get(order.customer_id) if order else None
        c = (contact or "").strip().lower()
        ok = bool(customer) and (
            customer.id in self.session.verified_customers
            or (c != "" and c == customer.email)
            or (len(_digits(c)) >= 10 and _digits(c) == _digits(customer.phone))
        )
        if not ok:
            self.session.failed_verifications += 1
            return None, {"error": "No order found matching those details. (Never say which detail was wrong.) "
                                   "Ask the customer to double-check the order number and the e-mail or phone used in the purchase."}
        if customer.id not in self.session.verified_customers:
            self.session.verified_customers.append(customer.id)
        return order, None

    def get_order_status(self, order_id: int, contact: str = "") -> dict:
        """Status, items, total, tracking code and delivery estimate of an order. REQUIRES the order number AND
        the e-mail or phone registered on the purchase (privacy/LGPD). Ask the customer for both if missing.
        Never reveal order data without a successful match.

        Args:
            order_id: order number given by the customer.
            contact: customer's e-mail or phone used in the purchase.
        """
        order, err = self._authorize(order_id, contact)
        if err:
            return err
        today = self.clock().date()
        customer = self.store.customers[order.customer_id]
        out: dict = {
            "order_id": order.id, "customer_first_name": customer.name.split()[0],
            "ordered_on": order.date.strftime("%d/%m/%Y"), "status": order.status, "status_pt": STATUS_PT[order.status],
            "items": [{"name": self.store.products[i.product_id].name, "quantity": i.quantity} for i in order.items],
            "total": brl(order.total), "payment": _payment_label(order.payment_method),
        }
        if order.tracking_code:
            out["tracking_code"] = order.tracking_code
            out["tracking_hint"] = "Track on the Correios or Jadlog website with this code."
        if order.estimated_delivery:
            out["estimated_delivery"] = order.estimated_delivery.strftime("%d/%m/%Y")
        if order.notes:
            out["notes"] = order.notes
        attention = []
        if order.status == "shipped" and order.estimated_delivery and order.estimated_delivery < today:
            attention.append(f"Estimated delivery ({out['estimated_delivery']}) has PASSED. Apologise, share the tracking code, "
                             "and offer escalate_to_human.")
        age = (today - order.date).days
        if order.status == "pending" and age > 5:
            attention.append(f"Payment still unconfirmed {age} days after the order. Mention that unpaid orders can be cancelled "
                             "and offer a hand-off; do not promise anything.")
        if order.status == "confirmed" and age > 7:
            attention.append(f"Order confirmed {age} days ago but not shipped yet — unusually long. Apologise, offer a hand-off.")
        if attention:
            out["attention"] = attention
        return out

    def check_return_eligibility(self, order_id: int, reason: str, contact: str = "") -> dict:
        """Check whether an order can be returned/exchanged under the store policy, using the real order dates.
        Call this when the customer wants to return, get a refund, regrets the purchase, exchanges, or reports a
        defect on a SPECIFIC order. REQUIRES order number + e-mail/phone (same verification as get_order_status).

        Args:
            order_id: order number.
            reason: "regret" (changed mind / arrependimento), "defect" (manufacturing defect), or
                "preference" (exchange for another colour/model/size).
            contact: customer's e-mail or phone used in the purchase.
        """
        if reason not in ("regret", "defect", "preference"):
            return {"error": "reason must be 'regret', 'defect' or 'preference'."}
        order, err = self._authorize(order_id, contact)
        if err:
            return err
        res = rules.return_eligibility(order, reason, self.clock().date())
        res["items"] = [self.store.products[i.product_id].name for i in order.items]
        res["next_step"] = ("If the customer wants to proceed, call escalate_to_human to open the return/exchange request; "
                            "you cannot execute it yourself.")
        return res

    # ------------------------------------------------------------------ hand-off
    def escalate_to_human(self, reason: str, summary: str, contact: str = "") -> dict:
        """Open a ticket for the human team. Use when: the customer complains; wants to actually START a return/
        exchange/cancellation; needs special freight or a quote; the policy does not cover the situation; data is
        missing; the customer asks for a human; or verification keeps failing. Never invent a promise instead.

        Args:
            reason: one of "complaint", "return_or_exchange", "special_freight", "policy_gap", "other".
            summary: short, factual summary of the case in Portuguese (order number, product, what the customer wants).
            contact: how the team can reach the customer (phone/e-mail), only if the customer agreed to share it.
        """
        now = self.clock()
        ticket = f"T-{now:%Y%m%d%H%M%S}"
        rec = {"ticket": ticket, "created_at": now.isoformat(), "reason": reason, "summary": summary,
               "contact": contact, "session": self.session.id}
        path = self.var_dir / "handoffs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        follow_up = ("A equipe retorna em até 24 horas úteis." if reason == "complaint"
                     else "Um atendente da equipe continua o atendimento no horário comercial.")
        return {"ticket": ticket, "follow_up": follow_up, "store_status": rules.store_status(now)}
