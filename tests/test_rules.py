from datetime import date, datetime

import pytest

from emporio import rules
from emporio.config import STORE_TZ
from emporio.text import brl


def test_brl_format():
    assert brl(5519.08) == "R$ 5.519,08"
    assert brl(159.9) == "R$ 159,90"


def test_promotion_shows_original_and_blocks_pix_discount(store):
    info = rules.price_info(store, store.products[94])  # Taylor 110e, 8% active promo
    assert info["promotion"]["promo_price"] == "R$ 5.519,08"
    assert info["promotion"]["original_price"] == "R$ 5.999,00"
    assert info["pix_price"] is None  # manual §6.2: PIX discount never stacks on promotions


def test_pix_discount_on_regular_price(store):
    info = rules.price_info(store, store.products[95])  # Takamine GD20, no promo
    assert info["pix_price"] == "R$ 2.089,05"


def test_expired_promotion_is_ignored(store):
    # product 96 has two promotions, both is_active = 0
    assert store.active_promotion(96) is None


@pytest.mark.parametrize("amount,expected_max", [(159.9, 3), (359.0, 4), (599.0, 6), (2199.0, 12), (30.0, 1)])
def test_installment_limits(amount, expected_max):
    # 3x needs >= R$50/installment, 4-6x >= R$80, 7-12x >= R$100 (manual §3.1)
    assert rules.installment_options(amount)["max_installments"] == expected_max


def test_shipping_local_threshold():
    assert rules.shipping_info("Campo Grande", 499.0)["delivery"]["fee"] == "R$ 35,00"
    assert rules.shipping_info("campo grande", 500.0)["delivery"]["fee"] == "grátis"
    assert "options" in rules.shipping_info("Dourados", 900)["delivery"]


def test_store_hours():
    sat_after = datetime(2026, 11, 7, 15, 0, tzinfo=STORE_TZ)
    r = rules.store_status(sat_after)
    assert r["open_now"] is False and "segunda-feira" in r["next_opening"]
    assert rules.store_status(datetime(2026, 11, 6, 10, 0, tzinfo=STORE_TZ))["open_now"] is True  # Friday
    assert rules.store_status(datetime(2026, 11, 7, 12, 59, tzinfo=STORE_TZ))["open_now"] is True  # Sat < 13h
    assert rules.store_status(datetime(2026, 12, 25, 10, 0, tzinfo=STORE_TZ))["open_now"] is False  # holiday


def test_regret_window(store):
    order = store.orders[7]  # delivered, received 2026-02-17
    assert rules.return_eligibility(order, "regret", date(2026, 2, 24))["eligible"] is True   # day 7
    assert rules.return_eligibility(order, "regret", date(2026, 2, 25))["eligible"] is False  # day 8


def test_defect_window_counts_from_purchase(store):
    order = store.orders[7]  # purchased 2026-02-03
    assert rules.return_eligibility(order, "defect", date(2026, 3, 5))["eligible"] is True
    late = rules.return_eligibility(order, "defect", date(2026, 3, 6))
    assert late["eligible"] is False and late["legal_warranty_active"] is True


def test_unshipped_and_cancelled_orders(store):
    assert rules.return_eligibility(store.orders[10], "regret", date(2026, 3, 1))["policy_gap"] is True
    assert rules.return_eligibility(store.orders[17], "regret", date(2026, 3, 1))["eligible"] is False
    assert rules.return_eligibility(store.orders[8], "regret", date(2026, 3, 1))["eligible"] is None  # in transit
