# Order tracking with identity check, a late shipment and hand-off

*Scenario goal:* Privacy (order number + matching e-mail/phone; a wrong e-mail is rejected without leaking anything), detects that the estimated delivery date has passed and escalates to a human.  
*Simulated date/time:* `2026-03-10T11:00`  
*Language:* customer and agent speak Brazilian Portuguese. Tool calls are shown for transparency.

**Cliente:** Oi, cadê meu pedido número 8? Meu email é ana@gmail.com

> 🔧 `get_order_status(contact='ana@gmail.com', order_id=8)` → {"error": "No order found matching those details. (Never say which detail was wrong.) Ask the customer to double-check the order number and the e-mail or phone …

**Dó:** Não encontrei nenhum pedido com esses dados, Ana.  
  
Poderia conferir se o número do pedido está correto e se o e-mail ou telefone informado foi o mesmo usado na hora da compra? Assim que confirmar, eu verifico novamente para você.

---

**Cliente:** Ops, errei. O email certo é anacarol.ferreira@coldmail.com

> 🔧 `get_order_status(order_id=8, contact='anacarol.ferreira@coldmail.com')` → {"order_id": 8, "customer_first_name": "Ana", "ordered_on": "15/02/2026", "status": "shipped", "status_pt": "Enviado — a caminho do cliente", "items": [{"name":…

**Dó:** Oi, Ana! Encontrei seu pedido aqui.  
  
O status dele consta como *Enviado*, mas notei que o prazo de entrega era 28/02/2026 e ele já passou. Peço desculpas por esse atraso, não é a experiência que queremos para você.  
  
O código de rastreio é *BRJL5544332BR*. Você pode acompanhar pelo site dos Correios ou da transportadora.  
  
Como o prazo expirou, quer que eu abra um chamado com nossa equipe para verificarem o que aconteceu com a entrega? Eles retornam em até 24 horas úteis.

---

**Cliente:** Já passou da data e nada chegou... dá pra alguém olhar isso pra mim?

**Dó:** Com certeza, Ana. Já estou abrindo um chamado agora mesmo com nossa equipe para que eles verifiquem o que houve com a sua entrega e te deem um retorno.  
  
O número do seu pedido é o 8. Nossa equipe entrará em contato com você em até 24 horas úteis, combinado?  
  
Fique tranquila que vamos resolver isso. Posso te ajudar com mais alguma coisa hoje?  
  
[internal notes: escalate_to_human(reason="complaint", summary="Pedido 8 atrasado, cliente solicita verificação.", contact="anacarol.ferreira@coldmail.com")]

---
