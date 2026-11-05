# Empório da Música — Agente de Atendimento ao Cliente

> 🇧🇷 Português · 🇺🇸 [English](README.md)

Um agente de chat por texto para a **Empório da Música**, uma loja (fictícia) de instrumentos musicais em Campo Grande/MS.
Ele atende os clientes como "Dó", um assistente simpático da loja, e decide sozinho **quando consultar dados em tempo real**
(preços, promoções, estoque, pedidos) e **quando consultar o manual de políticas** (trocas, pagamentos, frete, garantia).

Feito para o case técnico de *AI Engineer* da Artefact. Python, API do Gemini (plano gratuito), sem framework além do SDK oficial.

```
Cliente: Quanto custa o Takamine GD20? Dá pra parcelar?
Dó:      O Takamine GD20 Dreadnought Natural custa R$ 2.199,00 (R$ 2.089,05 no PIX).
         No cartão, até 12x de R$ 183,25 sem juros. Quer calcular o frete pra sua cidade? 🎸
```

* **Conversas de exemplo:** [`examples/`](examples) (5 cenários roteirizados, gerados rodando o agente real — veja abaixo)
* **Testes:** 30 testes determinísticos, sem precisar de chave de API (`pytest`)

---

## 1. Como rodar

Requisitos: Python 3.10+ e uma chave gratuita da API do Gemini ([crie aqui](https://aistudio.google.com/apikey), sem cartão de crédito).

```bash
git clone https://github.com/brayanferreiradev-gif/emporio-agent.git && cd emporio-agent
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # depois edite o .env e cole sua chave em GEMINI_API_KEY
python -m emporio             # comece a conversar
```

Opções úteis:

| Comando | O que faz |
|---|---|
| `python -m emporio --verbose` | também mostra cada chamada de ferramenta do agente (ótimo para ver o raciocínio) |
| `python -m emporio --session maria` | conversa com nome; o histórico é salvo em `var/sessions/maria.json` e retomado na próxima vez |
| `python -m emporio --new` | começa a sessão do zero (ou digite `/nova` no chat) |
| `python -m emporio --now 2026-03-05T15:00` | simula a data/hora atual (veja "Relógio" abaixo) |
| `pytest` | roda os testes (offline, < 1 s) |
| `python scripts/run_examples.py` | regera as conversas de exemplo (chamadas reais à API) |

Vale experimentar: *"Quais violões de aço até R$ 800?"*, *"Cadê meu pedido 8?"* (o agente pede e-mail/telefone —
use `anacarol.ferreira@coldmail.com`), *"Me arrependi, posso devolver o pedido 7?"*, *"Vocês vendem palheta?"*.

> **Relógio.** Os CSVs são uma foto congelada (último pedido: 22/03/2026), mas a data real é posterior, então todo pedido
> pareceria ter meses. `--now` / `EMPORIO_NOW` simula uma data; sem isso, usa-se o relógio real. Os exemplos usam essa opção.

---

## 2. Como funciona

```
 mensagem do cliente
        │
        ▼
 ┌──────────────────────────────  Agente (emporio/agent.py)  ────────────────────────────┐
 │  prompt de sistema (persona + regras)  +  últimas 24 mensagens  +  nova mensagem        │
 │        │                                                                               │
 │        ▼              chamada(s) de ferramenta                                         │
 │     Gemini  ───────────────────────────►  Ferramentas (emporio/tools.py)               │
 │        ▲                                   │  search_products · get_product_details    │
 │        └────────── resultados ◄────────────┤  get_payment_options · get_shipping_info  │
 │   (loop, no máx. 6 idas e vindas)          │  get_store_info · search_policies         │
 │                                            │  get_order_status · check_return_elig...  │
 │                                            └─ escalate_to_human                        │
 └────────────────────────────────────────────────────────────────────────────────────────┘
        │                                         │                       │
        ▼                                         ▼                       ▼
   resposta final                 data/*.csv (limpos em memória)   data/store_policies.md
   salva em var/sessions/                  + regras de negócio        (busca BM25 por seção)
```

| Arquivo | Papel |
|---|---|
| `emporio/agent.py` | Loop de function calling, fallback de modelos, tentativas, notas de memória da conversa |
| `emporio/prompts.py` | Persona, regras de fundamentação, guia de roteamento de ferramentas (dinâmico: data + visão do catálogo) |
| `emporio/tools.py` | As 9 ferramentas que o modelo pode chamar; verificação de identidade; tickets de transferência |
| `emporio/rules.py` | Regras de negócio em código puro: preço/PIX, parcelas, frete, horário, prazos de devolução |
| `emporio/catalog.py` | Busca de produtos insensível a acentos/plural, com peso por campo |
| `emporio/policies.py` | Busca BM25 no manual de políticas + tabela de sinônimos |
| `emporio/data.py` | Carga e limpeza dos CSVs, relatório de qualidade dos dados |
| `emporio/session.py` | Histórico persistente + estado de verificação por conversa |
| `scripts/ingest_policies.py` | Conversão do manual de PDF para Markdown (PyMuPDF, inclusive tabelas) |
| `scripts/run_examples.py` | Roda conversas roteirizadas contra o agente real → `examples/` |

---

## 3. Decisões técnicas e porquês

### Abordagem: function calling com ferramentas determinísticas (híbrido)
O case pede que o agente saiba *quando* consultar dados e *quando* consultar políticas. Function calling mapeia isso
diretamente: cada ferramenta é uma fonte de dados ou uma regra de negócio, e o modelo escolhe a(s) ferramenta(s) a partir da pergunta.
Descartei as alternativas de propósito:

* **RAG puro** sobre tudo: preços, estoque e pedidos são dados estruturados e precisam ser exatos. Recuperar trechos de texto de um CSV
  perde informação e convida a números inventados.
* **Agente text-to-SQL**: flexível, mas frágil (joins errados, filtro `is_active` esquecido, vazamento de pedidos de outros clientes) e
  inseguro para dados privados de pedidos. Um conjunto fixo de ferramentas parametrizadas cobre o mesmo escopo aqui com muito menos risco.
* **Loop ReAct em texto livre**: o tool calling nativo dá argumentos validados e chamadas paralelas sem precisar fazer parsing.

**As regras vivem no código, não no prompt.** Preço promocional, a regra "o desconto do PIX nunca acumula com promoção", parcelas
mínimas, o limite de frete grátis, horário de funcionamento e as janelas de 7/30 dias de devolução são funções simples em `rules.py`.
As ferramentas devolvem valores **já formatados** (`"R$ 5.519,08"`), então o modelo nunca faz conta nem cálculo de datas. Isso elimina a
classe mais comum de erros de LLM e deixa o comportamento testável por unidade (30 testes).

### Modelo e provedor: API do Gemini, plano gratuito
Considerei primeiro um modelo local de 7B via Ollama (grátis, privado). Na máquina de destino (GPU de notebook com 6 GB), um modelo 7B
seria lento e visivelmente menos confiável em tool calling em português, e a confiabilidade importa mais que a privacidade aqui,
porque os dados são fictícios. O Gemini tem plano gratuito, com function calling nativo forte e bom português.

Achados práticos durante a construção (planos gratuitos mudam rápido, então o código é defensivo):

* O `gemini-2.5-flash` retorna **404 "no longer available to new users"**, então não pode ser o padrão.
* Os modelos mais novos retornam **503 "high demand"** em rajadas. O `emporio/config.py` define uma **cadeia de fallback**
  (`gemini-3.6-flash → gemini-3.5-flash → gemini-3.1-flash-lite`, configurável com `GEMINI_MODEL` / `GEMINI_FALLBACK_MODELS`);
  o primeiro modelo saudável responde. As tentativas internas do SDK ficam limitadas a uma, porque esperar um modelo sobrecarregado
  levava 20 s ou mais, enquanto trocar de modelo leva ~1 s.
* **`thinking_level="low"`**: mesmas respostas, ~4× mais rápido nas minhas medições (≈7 s contra ≈30 s para uma pergunta de catálogo
  com uma chamada de ferramenta). Configurável com `GEMINI_THINKING`.

### Arquitetura de recuperação
* **Políticas**: o manual tem ~10 seções, então uma **busca BM25 por palavras-chave sobre trechos por seção**, com uma pequena tabela
  de sinônimos em português (ex.: *devolver → devolução/arrependimento*), basta. Sem banco vetorial, sem chamadas de embeddings, fácil de depurar.
  O PDF é convertido uma vez para Markdown por `scripts/ingest_policies.py` (PyMuPDF, com tabelas preservadas); em execução só se lê o `.md`.
* **Catálogo**: busca lexical com normalização de acentos/plural e pesos por campo (nome/marca > categoria > descrição/especificações).
  Números de modelo casam do jeito que forem digitados (`GD20`, `gd-20`, `gd 20`). Com ~65 itens e códigos de modelo, casamento quase exato vence embeddings.
  Produtos sem estoque, descontinuados e "em breve" voltam numa lista separada `matches_not_for_sale`, com alternativas
  (manual §7.3: nunca confirmar disponibilidade sem verificar, oferecer alternativas).

### Estratégia de prompt
O prompt de sistema (`prompts.py`) tem: persona e tom (do manual §7.1: *informal, mas profissional, como um amigo que entende de música*),
uma **regra de ouro** (qualquer coisa sobre preços/estoque/pedidos/políticas deve vir de um resultado de ferramenta nesta conversa; senão,
dizer "não sei" e oferecer um atendente humano), uma **tabela de roteamento** (qual pergunta → qual ferramenta) e **regras numeradas**
(exibição de promoção, disponibilidade, escopo, privacidade, devoluções, reclamações, resistência a injeção de prompt). Ele é dinâmico: injeta a data/hora
atual e uma visão de quais categorias realmente têm produtos, para o modelo não prometer instrumentos que a loja não lista.
As respostas seguem convenções de WhatsApp (curtas, `*negrito*`, no máximo um emoji).

### Privacidade e segurança
* Dados de pedido exigem **número do pedido + e-mail ou telefone que correspondam** (LGPD, manual §9). Uma verificação que falha devolve a mesma
  mensagem genérica, seja o pedido ou o contato que estava errado (sem vazar informação), e após 3 falhas o chat é bloqueado e o agente oferece um humano.
  A verificação de identidade está na ferramenta, **não** no prompt, então uma injeção de prompt não consegue contorná-la.
* O modelo não consegue executar devoluções, reembolsos ou cancelamentos; só pode abrir um **ticket de transferência** (`var/handoffs.jsonl`).
* Escopo: acessórios são redirecionados com educação, assuntos alheios à loja são recusados, e o manual é tratado como documento interno (parafraseado, não citado).
* Saída de ferramentas e texto do cliente são declarados no prompt como *dados, não instruções*.

### Interface e persistência
* **CLI** (o case diz que o foco é o agente funcionando). Uma interface mínima mantém a avaliação na lógica do agente.
* **Persistência**: um arquivo JSON por sessão (`var/sessions/<id>.json`) com histórico e estado de verificação, retomado automaticamente.
  O modelo vê as últimas 24 mensagens mais *notas internas* curtas do que as ferramentas devolveram (ex.: ids de produto), então perguntas como
  "me fala mais do mais barato" não disparam novas buscas. As notas nunca são mostradas ao cliente.

### Tratamento dos dados
`emporio/data.py` lê e limpa os CSVs; `quality_report()` lista o que foi encontrado (tudo coberto por testes):

| Achado | Tratamento |
|---|---|
| Produto 96 está `active` com estoque 0 | disponibilidade = `out_of_stock` |
| Produto 130 está `coming_soon` com estoque 2; produto 136 está `discontinued` com estoque 13 | nunca vendáveis; alternativas sugeridas |
| Categorias 6, 7, 8 (madeiras, metais, cordas orquestrais) **não têm produtos**, embora o manual diga que a loja vende | o agente diz que o catálogo não tem nada agora (dados do sistema valem mais que o manual) |
| 21 de 25 promoções têm `is_active = 0` (só 4 estão valendo) | só promoções ativas contam; as vencidas nunca são oferecidas |
| Pedidos 3 e 20: total registrado ≠ soma dos itens a preços atuais | o total registrado é usado como está |
| O e-mail `bruno.martins@jmail.com` pertence a dois clientes (11 e 43) | a verificação exige que **pedido + contato** pertençam ao mesmo cliente, nunca o contato sozinho |
| Pedidos com data posterior ao "agora" simulado | tratados como inexistentes |

---

## 4. Suposições (ambiguidades e contradições no material)

1. **Telefone/WhatsApp.** O manual traz `(67) 3341-4444` (capa e dados da empresa) e `(67) 3321-4500` (seção de WhatsApp). Uso **3341-4444** em todo lugar
   (`policies.CANONICAL_FIXES`) para o agente nunca dar duas respostas. Da mesma forma, o e-mail é escrito sem acento (`contato@emporiodamusica.com.br`).
2. **Parcelamento.** A tabela-resumo diz "parcela mínima de R$ 100"; a §3.1 é mais específica (até 3x a partir de R$ 50, 4–6x a partir de R$ 80, 7–12x a partir de R$ 100). Implementei a **§3.1**.
3. **Região de entrega.** "Região metropolitana de Campo Grande" não é definida; só **Campo Grande** é tratada como local (taxa fixa de R$ 35 abaixo de R$ 500, grátis a partir de R$ 500).
   Outras cidades recebem a tabela Correios/Jadlog e um aviso de que o valor exato depende do CEP (não calculável aqui).
4. **Devoluções.** Não há coluna de canal, então todos os pedidos são tratados como **online** (vale o direito de arrependimento da §4.1). Não há data de entrega efetiva, então,
   para pedidos entregues, `estimated_delivery` faz o papel da data de recebimento. A janela de 30 dias para troca por defeito é contada **a partir da compra**, como a §4.2 diz literalmente;
   a garantia legal de 90 dias a partir do recebimento é informada quando relevante.
5. **Pedidos não enviados.** O manual não tem política de cancelamento, então o agente diz isso e transfere para um humano em vez de improvisar.
6. **Feriados.** Só feriados nacionais de data fixa entram na resposta de "vocês estão abertos?"; os móveis (Carnaval, Sexta-feira Santa) não são rastreados.
7. **Lojas parceiras.** O manual diz para sugerir lojas parceiras "quando possível", mas não existe lista; o agente recomenda "lojas especializadas em acessórios" sem inventar nomes.
8. **Transferência para humano.** Não há sistema de tickets, então os tickets são gravados num arquivo local (`var/handoffs.jsonl`) como substituto.

---

## 5. Conversas de exemplo

Geradas por `scripts/run_examples.py` — modelo real, ferramentas reais, mensagens do cliente roteirizadas, uma data simulada por cenário, nada editado à mão.
Cada arquivo mostra as chamadas de ferramenta (🔧) abaixo de cada mensagem do cliente. Os arquivos têm descrição em inglês e a conversa em português.

| Arquivo | O que demonstra |
|---|---|
| [`01_catalog_and_payment`](examples/01_catalog_and_payment.md) | Busca por orçamento no catálogo real, pergunta seguinte sem nova busca, parcelas e PIX |
| [`02_price_promotion_and_hours`](examples/02_price_promotion_and_hours.md) | Consulta de preço, promoção ativa mostrada com preço original e %, "estão abertos agora?" num sábado à tarde |
| [`03_order_tracking_delay`](examples/03_order_tracking_delay.md) | Verificação de identidade (e-mail errado rejeitado), atraso na entrega detectado, ticket de transferência |
| [`04_return_policy`](examples/04_return_policy.md) | **Não trivial:** prazo de arrependimento vencido (16 dias), mas janela de troca por defeito (30 dias da compra) ainda aberta; depois abre a solicitação |
| [`05_scope_and_guardrails`](examples/05_scope_and_guardrails.md) | Acessórios redirecionados, assunto alheio recusado, promoção vencida de Black Friday não prometida, injeção de prompt recusada |

---

## 6. Limitações conhecidas e o que eu faria com mais tempo

* **Latência e disponibilidade** dependem do plano gratuito do Gemini: as respostas levam ~3–15 s e a cadeia de fallback pode trocar de modelo entre turnos
  (as respostas continuam consistentes porque as regras estão no código, mas o tom pode variar um pouco).
* **Sem avaliação automatizada do LLM.** O código determinístico é bem testado, mas o comportamento do modelo é verificado só pelas conversas de exemplo. Próximo passo: um pequeno
  conjunto de ~50 conversas roteirizadas com asserções sobre as chamadas de ferramenta e um LLM-as-judge para o tom, rodando em CI.
* **A recuperação é lexical.** Serve para 65 produtos e 10 seções do manual; eu adicionaria embeddings (busca híbrida) quando o catálogo chegar aos 300+ itens que o manual menciona.
* **Frete fora de Campo Grande** não pode ser calculado; eu integraria as APIs de cotação dos Correios/Jadlog por CEP.
* **A transferência para humano é um arquivo.** Uma versão real criaria um ticket no helpdesk/CRM, notificaria a equipe e coletaria o consentimento de contato de forma explícita.
* **Canal único, usuário único (CLI).** A mesma classe `Agent` poderia ficar atrás de um FastAPI/webhook de WhatsApp; as sessões sairiam de arquivos JSON para um banco de dados.
* **Streaming e observabilidade.** Transmitir as respostas em streaming para reduzir a latência percebida; enviar traces (chamadas de ferramenta, tokens, latência) para um backend de tracing.
* **Feriados e calendário da loja** deveriam vir de uma fonte de calendário em vez de uma lista fixa.
* **Atualidade de preço/estoque**: os dados são carregados uma vez na inicialização; numa implantação real, leem-se do sistema ao vivo a cada chamada.

---

## 7. Uso de assistentes de código com IA

Construí isto com o **Claude Code** (agente de código da Anthropic para CLI/desktop, modelo *Claude Sonnet 5.5*) como par de programação, trabalhando em iterações curtas.
Como o trabalho foi dividido:

* **Minhas decisões:** o escopo da entrega, a escolha de um modelo via API em vez de um 7B local (hardware e confiabilidade), o Gemini como provedor, o local do projeto e a revisão de cada etapa.
* **Claude Code:** leu o enunciado, o manual (PDF) e os CSVs; propôs a arquitetura; escreveu o código, os testes e este README;
  rodou o código contra a API real e iterou sobre o que observou.
* **Coisas descobertas rodando, não adivinhando:** o `gemini-2.5-flash` foi aposentado para chaves novas (404); os modelos mais novos ficam sobrecarregados de vez em quando (→ cadeia de fallback);
  `thinking_level="low"` cortou a latência em ~4×; as primeiras respostas do modelo usavam `**negrito**` (→ o prompt agora pede formatação de WhatsApp); o agente esquecia os ids de produto entre
  turnos e buscava de novo (→ notas internas no histórico); um teste que o assistente escreveu com expectativa errada (599 ÷ 6 ≥ R$ 80 → 6 parcelas, não 5) foi pego pela execução dos testes.
* **Verificação:** toda regra de negócio tem um teste unitário; as transcrições de exemplo vêm do agente real, sem edição.

O histórico de commits mostra a progressão real (estrutura → dados/ingestão → regras/ferramentas/agente → resiliência → testes → exemplos → documentação).

---

## 8. Estrutura do projeto

```
emporio/            pacote do agente (veja a tabela na seção 2)
data/               CSVs + store_policies.pdf (fonte) + store_policies.md (gerado)
scripts/            ingest_policies.py, run_examples.py
tests/              suíte pytest (offline)
examples/           conversas de exemplo geradas
var/                estado em execução: sessões, tickets de transferência (ignorado pelo git)
```
