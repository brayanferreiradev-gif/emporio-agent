import json

from emporio import catalog
from emporio.data import quality_report


def test_data_cleaning(store):
    assert len(store.products) == 65 and len(store.orders) == 20
    assert store.products[96].availability == "out_of_stock"      # active but stock 0
    assert store.products[130].availability == "coming_soon"      # stock 2 but not on sale
    assert store.products[136].availability == "discontinued"     # stock 13 but discontinued
    assert any("Order 3" in f for f in quality_report(store))


def test_search_specific_model_any_spelling(store):
    for q in ("Takamine GD20", "takamine gd-20", "gd 20"):
        assert [p.id for p, _ in catalog.search(store, q)][:1] == [95]


def test_budget_filter_uses_effective_price(store):
    ids = {p.id for p, _ in catalog.search(store, "violão", max_price=1000)}
    assert 83 in ids and 92 not in ids  # 429.90 yes, 1299 no
    # product 90 costs 2399 but has an 18% active promotion -> 1967.18, still above 1500
    assert 90 not in {p.id for p, _ in catalog.search(store, "crafter", max_price=1500)}


def test_category_without_products(make_tools):
    out = make_tools().search_products(category="sopro")
    assert out["results"] == [] and "NO products" in out["note"]


def test_unavailable_product_is_flagged_with_alternatives(make_tools):
    out = make_tools().search_products(query="Giannini GF-3D")
    flagged = out["matches_not_for_sale"][0]
    assert flagged["availability"] == "out_of_stock" and flagged["alternatives"]


def test_accessory_query_gets_scope_warning(make_tools):
    assert "scope_warning" in make_tools().search_products(query="palheta")
    assert "scope_warning" not in make_tools().search_products(query="violão 7 cordas")


def test_order_requires_matching_contact(make_tools):
    t = make_tools()
    assert "error" in t.get_order_status(7, "")
    assert "error" in t.get_order_status(7, "someone@else.com")
    ok = t.get_order_status(7, "(67) 99789-0123")  # phone, any formatting
    assert ok["customer_first_name"] == "Letícia" and ok["total"] == "R$ 159,90"


def test_error_does_not_leak_which_field_failed(make_tools):
    t = make_tools()
    wrong_order = t.get_order_status(9999, "leticia.rocha@jmail.com")
    wrong_contact = t.get_order_status(7, "x@y.com")
    assert wrong_order["error"] == wrong_contact["error"]


def test_lockout_after_three_failures(make_tools):
    t = make_tools()
    for _ in range(3):
        t.get_order_status(1, "nope@x.com")
    assert "Too many" in t.get_order_status(1, "pedro.oliveira@jmail.com")["error"]


def test_shared_email_needs_matching_order(make_tools):
    # bruno.martins@jmail.com belongs to customers 11 AND 43, but an order only matches its own customer
    t = make_tools("2026-03-01T10:00")
    assert t.get_order_status(10, "bruno.martins@jmail.com")["order_id"] == 10  # customer 11's order


def test_future_orders_do_not_exist(make_tools):
    # order 20 is dated 2026-03-08; with the clock at 2026-02-20 it must not be visible
    assert "error" in make_tools("2026-02-20T10:00").get_order_status(20, "thiago.barbosa@jmail.com")


def test_overdue_shipment_is_flagged(make_tools):
    out = make_tools("2026-03-10T10:00").get_order_status(8, "anacarol.ferreira@coldmail.com")
    assert "PASSED" in out["attention"][0]


def test_return_check_end_to_end(make_tools):
    out = make_tools().check_return_eligibility(7, "regret", "leticia.rocha@jmail.com")
    assert out["eligible"] is True and out["items"] == ["Shelby SU-21S Soprano Sunburst"]


def test_escalation_writes_ticket(make_tools, tmp_path):
    out = make_tools().escalate_to_human("complaint", "Cliente insatisfeito com atraso")
    assert out["ticket"].startswith("T-") and "24 horas úteis" in out["follow_up"]
    rec = json.loads((tmp_path / "handoffs.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["reason"] == "complaint"


def test_policy_retrieval_routes_to_right_section(policies):
    def top(q):
        return policies.search(q, 1)[0][0].ref
    assert top("posso devolver meu pedido, me arrependi") == "4.1"
    assert top("vocês aceitam pix? parcelam em quantas vezes") in ("3", "3.1")
    assert top("que horas vocês abrem no sábado") == "2"
    assert top("vocês vendem cordas e palhetas?") == "1"
    assert top("qual o prazo de entrega") in ("5.1", "5")


def test_policy_text_has_single_phone_number(policies):
    text = " ".join(s.text for s in policies.sections)
    assert "3321-4500" not in text and "3341-4444" in text


def test_list_promotions_returns_every_active_one(make_tools):
    out = make_tools().list_promotions()
    names = " ".join(i["name"] for i in out["items"])
    assert out["active_promotions"] == 4
    for expected in ("Ohana CK-20", "Crafter HT-100", "Taylor 110e", "Kalani KAL-700T"):
        assert expected in names
    assert all("promotion" in i for i in out["items"])


def test_sort_by_price(make_tools):
    t = make_tools()
    top = t.search_products(sort_by="price_desc")["results"][0]
    cheapest = t.search_products(category="ukuleles", sort_by="price_asc")["results"][0]
    assert "Nord Synth 2 Pro" in top["name"] and "Shelby SU-21S" in cheapest["name"]


def test_combined_payment_rule_is_explained(make_tools):
    t = make_tools()
    small = t.get_payment_options(81)  # Yamaha C40, R$ 599,90
    big = t.get_payment_options(95)    # Takamine GD20, R$ 2.199,00
    assert small["combine_payment_methods_allowed"] is False and "NOT" in small["combine_payment_methods_rule"]
    assert big["combine_payment_methods_allowed"] is True


def test_whatsapp_bold_conversion():
    from emporio.agent import whatsapp_format
    assert whatsapp_format("O **Yamaha F310** custa **R$ 699,90**") == "O *Yamaha F310* custa *R$ 699,90*"
    assert whatsapp_format("*já certo*") == "*já certo*"


def test_internal_notes_never_reach_the_customer():
    from emporio.agent import whatsapp_format
    leaked = "O Yamaha custa R$ 699,90.\n\n[internal notes product_id: 87]"
    assert whatsapp_format(leaked) == "O Yamaha custa R$ 699,90."
    assert whatsapp_format("Ok [internal notes search_products: category=Guitarras]") == "Ok"


def test_notes_go_to_system_prompt_not_to_messages(store):
    from datetime import datetime
    from emporio.prompts import build_system_prompt
    p = build_system_prompt(store, datetime(2026, 3, 23, 10), "products mentioned: id 87 = Yamaha F310")
    assert "id 87 = Yamaha F310" in p and "Already looked up" in p


def test_general_returns_question_sees_defect_section(policies):
    refs = [s.ref for s, _ in policies.search("política de troca e devolução", 3, expand=True)]
    assert "4.2" in refs  # manufacturing-defect swap (30 days) must not be dropped


def test_search_results_carry_instalment_hint(make_tools):
    top = make_tools().search_products(query="Takamine GD20")["results"][0]
    assert "12x de R$ 183,25" in top["instalments"]


def test_language_detection():
    from emporio.text import detect_language
    assert detect_language("Hello, do you sell guitars?") == "en"
    assert detect_language("¿Tienen guitarras? Hola") == "es"
    assert detect_language("Quanto custa o Takamine GD20?") == "pt"
    assert detect_language("oi") == "pt" and detect_language("🎸") == "pt" and detect_language("") == "pt"
    assert detect_language("Pedido 8, meu email é ana@gmail.com") == "pt"
