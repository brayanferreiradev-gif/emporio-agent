"""Business rules from the store manual, implemented as deterministic code.

Why code and not "ask the LLM": prices, installments, shipping fees and return windows are
arithmetic/date logic. A model gets them wrong sometimes; a function never does, and it can
be unit-tested. The LLM only decides *which* rule to call and phrases the answer.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .data import Order, Product, Store
from .text import brl, normalize

PIX_DISCOUNT = 0.05
FREE_SHIPPING_FROM = 500.0
LOCAL_SHIPPING_FEE = 35.0
LOCAL_CITIES = {"campo grande"}  # ASSUMPTION: manual does not list the metropolitan-region towns
REGRET_DAYS = 7
DEFECT_SWAP_DAYS = 30
LEGAL_WARRANTY_DAYS = 90

STORE_INFO = {
    "name": "Empório da Música",
    "address": "Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333",
    "phone_whatsapp": "(67) 3341-4444",
    "email": "contato@emporiodamusica.com.br",
}
# Mon..Sat opening windows (weekday() -> (open, close)); Sunday/holidays closed.
HOURS = {**{d: (time(9), time(18)) for d in range(5)}, 5: (time(9), time(13))}
HOURS_TEXT = "Segunda a sexta, 09h–18h · Sábado, 09h–13h · Domingo e feriados: fechado"
# Fixed-date national holidays only; movable ones (Carnival, Good Friday...) are not tracked.
FIXED_HOLIDAYS = {(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)}
WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


# --------------------------------------------------------------------------- pricing
def price_info(store: Store, p: Product) -> dict:
    """Price block following manual §6.2: promo shown with original price + percentage;
    no PIX discount on top of a promotional price."""
    promo = store.active_promotion(p.id)
    final = round(p.price * (1 - promo.percent / 100), 2) if promo else p.price
    info: dict = {"list_price": brl(p.price)}
    if promo:
        info["promotion"] = {
            "name": promo.label, "discount_percent": promo.percent,
            "original_price": brl(p.price), "promo_price": brl(final),
        }
        info["pix_price"] = None
        info["pix_note"] = "5% PIX discount does not apply on top of promotional prices."
    else:
        info["pix_price"] = brl(round(p.price * (1 - PIX_DISCOUNT), 2))
    info["price_to_pay"] = brl(final)
    info["price_value"] = final
    return info


def _min_installment(n: int) -> float:
    # Manual §3.1 (more specific than the summary table, which says R$100 for everything):
    return 50.0 if n <= 3 else 80.0 if n <= 6 else 100.0


def installment_options(amount: float) -> dict:
    allowed = [n for n in range(1, 13) if n == 1 or amount / n >= _min_installment(n)]
    top = max(allowed)
    return {
        "max_installments": top,
        "max_installments_value": brl(round(amount / top, 2)),
        "options": [{"installments": n, "value": brl(round(amount / n, 2))} for n in (1, 2, 3, 6, 10, 12) if n in allowed],
        "interest": "none (sem juros)",
    }


def payment_options(store: Store, p: Product, quantity: int = 1) -> dict:
    info = price_info(store, p)
    total = round(info["price_value"] * quantity, 2)
    out = {
        "product": p.name, "quantity": quantity, "total_to_pay": brl(total),
        "credit_card": installment_options(total),
        "debit_card": f"à vista, {brl(total)} (todas as bandeiras)",
        "boleto": f"à vista, {brl(total)} (compensação em até 3 dias úteis)",
        "combine_payment_methods": total > 2000,
    }
    if "promotion" in info:
        out["pix"] = f"à vista, {brl(total)} (preço promocional; sem desconto extra de PIX)"
    else:
        out["pix"] = f"à vista, {brl(round(p.price * quantity * (1 - PIX_DISCOUNT), 2))} (5% de desconto sobre o preço de tabela)"
    return out


# --------------------------------------------------------------------------- shipping
def shipping_info(city: str | None, order_value: float | None, large_item: bool = False) -> dict:
    local = {
        "region": "Campo Grande (entrega por motoboy próprio)",
        "deadline": "1 a 3 dias úteis; o cliente recebe uma ligação antes da entrega",
        "fee": "grátis" if (order_value or 0) >= FREE_SHIPPING_FROM else brl(LOCAL_SHIPPING_FEE),
        "rule": f"Frete grátis em pedidos a partir de {brl(FREE_SHIPPING_FROM)}; abaixo disso, taxa fixa de {brl(LOCAL_SHIPPING_FEE)}.",
    }
    other = {
        "region": "Outras cidades (Correios / Jadlog)",
        "options": [
            {"carrier": "PAC (Correios)", "deadline": "5 a 12 dias úteis"},
            {"carrier": "SEDEX (Correios)", "deadline": "2 a 5 dias úteis"},
            {"carrier": "Jadlog (.package)", "deadline": "3 a 8 dias úteis"},
        ],
        "fee": "calculado automaticamente pelo CEP, peso e dimensões — não consigo cotar aqui",
        "extras": "Todos os envios têm rastreamento e seguro incluídos.",
    }
    if large_item:
        other["large_item"] = "Item de grande porte: pode exigir frete especial com cotação individual (encaminhar para a equipe)."
    if city is None:
        return {"campo_grande": local, "other_cities": other, "note": "Ask the customer's city to pick one."}
    if normalize(city) in LOCAL_CITIES:
        return {"delivery": local}
    other["note"] = "City not confirmed as Campo Grande metropolitan area; if unsure, the team confirms the carrier."
    return {"delivery": other}


# --------------------------------------------------------------------------- opening hours
def _is_open_day(d: date) -> bool:
    return d.weekday() in HOURS and (d.month, d.day) not in FIXED_HOLIDAYS


def store_status(dt: datetime) -> dict:
    """Is the store open at ``dt`` and, if not, when does it open next?"""
    open_now = False
    if _is_open_day(dt.date()):
        start, end = HOURS[dt.weekday()]
        open_now = start <= dt.time() < end
    nxt = None
    for offset in range(0, 9):
        day = dt.date() + timedelta(days=offset)
        if not _is_open_day(day):
            continue
        start, _ = HOURS[day.weekday()]
        if datetime.combine(day, start, tzinfo=dt.tzinfo) > dt:
            nxt = day, start
            break
    out = {
        "now": dt.strftime("%d/%m/%Y %H:%M") + f" ({WEEKDAYS[dt.weekday()]})",
        "open_now": open_now,
        "hours": HOURS_TEXT,
    }
    if not open_now and nxt:
        out["next_opening"] = f"{WEEKDAYS[nxt[0].weekday()]}, {nxt[0].strftime('%d/%m')} às {nxt[1].strftime('%Hh')}"
    out["holiday_note"] = "Only fixed-date national holidays are tracked; confirm movable holidays if relevant."
    return out


# --------------------------------------------------------------------------- returns & exchanges
def return_eligibility(order: Order, reason: str, today: date) -> dict:
    """Apply manual §4 to an order. ``reason``: regret | defect | preference.

    ASSUMPTIONS (documented in README): every order is an online/remote purchase (the data has no
    channel column, so §4.1 applies); there is no delivery timestamp, so ``estimated_delivery`` is
    used as the receipt date of delivered orders.
    """
    base = {"order_id": order.id, "order_status": order.status, "reason": reason}
    if order.status == "cancelled":
        return {**base, "eligible": False, "explanation": "Order was cancelled, so there is nothing to return."}
    if order.status in ("pending", "confirmed"):
        return {**base, "eligible": None, "policy_gap": True,
                "explanation": "Order not shipped yet. The manual has no cancellation rule for unshipped orders: "
                               "do not promise anything, hand off to the team."}
    if order.status == "shipped":
        return {**base, "eligible": None,
                "explanation": "Order is still in transit. The 7-day regret window only starts when the customer "
                               "RECEIVES the product. If it arrives damaged, refuse delivery and contact the store immediately."}

    received = order.estimated_delivery or order.date
    since_receipt = (today - received).days
    since_purchase = (today - order.date).days
    context = {"received_on_assumed": received.isoformat(), "days_since_receipt": since_receipt,
               "days_since_purchase": since_purchase}
    conditions = ["Original packaging, no signs of use, with all accessories and manuals."]

    if reason in ("regret", "preference"):
        ok = since_receipt <= REGRET_DAYS
        res = {**base, **context, "eligible": ok, "window_days": REGRET_DAYS, "conditions": conditions}
        if reason == "regret":
            res["explanation"] = (f"Regret window is {REGRET_DAYS} days from receipt; {since_receipt} days have passed."
                                  if not ok else f"Within the {REGRET_DAYS}-day regret window ({since_receipt} days since receipt).")
            if ok:
                res["benefits"] = ["Refund to the original payment method within 10 business days.", "Return shipping paid by the store."]
        else:
            res["explanation"] = (f"Exchange by preference allowed within {REGRET_DAYS} days, subject to the wanted product being in stock; "
                                  f"{since_receipt} days have passed." if not ok else
                                  "Within the exchange window; depends on stock of the desired item. Price difference is charged or refunded.")
        return res

    # defect
    in_swap = since_purchase <= DEFECT_SWAP_DAYS
    in_legal = since_receipt <= LEGAL_WARRANTY_DAYS
    res = {**base, **context, "eligible": in_swap, "window_days": DEFECT_SWAP_DAYS,
           "conditions": ["Manufacturing defect only. Misuse, drops, humidity or unauthorised changes are not covered."]}
    if in_swap:
        res["explanation"] = f"Manufacturing-defect swap is allowed within {DEFECT_SWAP_DAYS} days of purchase ({since_purchase} days so far)."
    else:
        res["explanation"] = (f"{since_purchase} days since purchase: past the {DEFECT_SWAP_DAYS}-day store swap window. "
                              f"The customer should use the manufacturer warranty; the store can mediate on request. "
                              + (f"Legal warranty ({LEGAL_WARRANTY_DAYS} days from receipt) is still running." if in_legal
                                 else f"Legal warranty ({LEGAL_WARRANTY_DAYS} days from receipt) has also expired."))
        res["legal_warranty_active"] = in_legal
    return res
