# Price check, an active promotion, and opening hours on a Saturday afternoon

*Scenario goal:* Promotion shown with original price + percentage, no PIX discount on promo prices, and 'are you open now?' computed from the clock (store closes at 13h on Saturdays).  
*Simulated date/time:* `2026-03-14T14:00`  
*Language:* customer and agent speak Brazilian Portuguese. Tool calls are shown for transparency.

**Cliente:** Boa tarde! Quanto custa o Takamine GD20?

> 🔧 `search_products(category='Violões', query='Takamine GD20')` → {"total_available_matches": 1, "results": [{"product_id": 95, "name": "Takamine GD20 Dreadnought Natural", "category": "Violões", "availability": "available", "…

**Dó:** Boa tarde! O Takamine GD20 Dreadnought Natural está disponível por R$ 2.199,00.  
  
Se preferir pagar via PIX, ele sai por R$ 2.089,05.  
  
Gostaria de saber mais detalhes sobre ele ou sobre as opções de parcelamento?

---

**Cliente:** E o violão Taylor 110e? Disseram que tá em promoção

> 🔧 `search_products(query='Taylor 110e')` → {"total_available_matches": 1, "results": [{"product_id": 94, "name": "Taylor 110e Dreadnought Natural", "category": "Violões", "availability": "available", "li…

**Dó:** O Taylor 110e Dreadnought Natural está, sim, com uma promoção ativa!  
  
Ele baixou de R$ 5.999,00 para R$ 5.519,08, o que representa um desconto de 8%.  
  
Como ele já está em oferta, o desconto adicional de 5% do PIX não se aplica neste caso. Quer que eu verifique as condições de parcelamento para você?

---

**Cliente:** Vocês estão abertos agora? Queria passar aí. Onde fica a loja?

> 🔧 `get_store_info()` → {"name": "Empório da Música", "address": "Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333", "phone_whatsapp": "(67) 3341-4444", "email": "contat…

**Dó:** Poxa, infelizmente nossa loja já fechou hoje! Aos sábados, atendemos das 09h às 13h.  
  
Nós reabriremos na segunda-feira, às 09h. Nossa loja fica na Rua 14 de Maio, 3200, no Centro.  
  
Se precisar de algo urgente ou quiser tirar mais alguma dúvida, pode mandar por aqui que na segunda a gente te responde. Combinado?

---
