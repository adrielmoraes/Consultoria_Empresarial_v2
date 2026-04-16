"""
Hive Mind — Gerador de Plano de Execução (PDF)
===============================================
Recebe o Markdown estruturado gerado pelo Marco e converte
em um PDF profissional com identidade visual Gold & Dark.

Versão 2: Cabeçalho e rodapé em TODAS as páginas via canvas hooks.
"""

import logging
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

logger = logging.getLogger("mentoria-ai.pdf")

# ─── Paleta de cores ───────────────────────────────────────────────────────────
GOLD     = colors.HexColor("#d4af37")
GOLD_DIM = colors.HexColor("#b08d24")
DARK_BG  = colors.HexColor("#0f1117")
DARK_MID = colors.HexColor("#1a1d2e")
DARK_CARD= colors.HexColor("#1e2138")
LIGHT_TXT= colors.HexColor("#e2e8f0")
BODY_TXT = colors.HexColor("#1e293b")  # Mais escuro, para fundo branco
MUTED_TXT= colors.HexColor("#94a3b8")
GREEN    = colors.HexColor("#10b981")
WHITE    = colors.white

PAGE_W, PAGE_H = A4
MARGIN_X = 20 * mm
MARGIN_T = 30 * mm  # espaço para o cabeçalho
MARGIN_B = 22 * mm  # espaço para o rodapé

CONTENT_WIDTH = PAGE_W - 2 * MARGIN_X

# ─── Prompts por tipo de documento ────────────────────────────────────────────

# ─── Prompt do Estrategista ────────────────────────────────────────────────────
SUMMARIZATION_PROMPT = """Você é Marco, o Estrategista-Chefe do Hive Mind — uma plataforma de mentoria empresarial multi-agentes de alto nível.
Com base na transcrição completa da sessão, gere um Plano de Execução ESTRATÉGICO, PROFUNDO e EXECUTÁVEL.

## INSTRUÇÕES CRÍTICAS DE QUALIDADE:

Antes de escrever qualquer seção, faça uma VERIFICAÇÃO INTERNA:
✅ Há metas SMART (Específicas, Mensuráveis, Atingíveis, Relevantes, com Tempo)?
✅ Há valores financeiros concretos em R$ (não apenas "a definir")?
✅ Há um cronograma com datas reais ou prazos em semanas/meses?
✅ Há divisão de responsabilidades com dono de cada ação?
✅ Há mapeamento de riscos E os planos de contingência?
Se algum item faltar, DETALHE antes de prosseguir.

## FORMATO OBRIGATÓRIO DO PLANO (8 seções + capa):

# Plano de Execução Estratégico — Hive Mind

## Resumo Executivo
[3 parágrafos: (1) O que o usuário quer construir e o potencial real do mercado, (2) proposta de valor única e diferenciação competitiva, (3) por que este momento é estratégico para entrar]

## Diagnóstico do Projeto
**Forças identificadas:**
- [força 1 com base na sessão]
- [força 2 com base na sessão]

**Principais desafios:**
- [desafio 1]
- [desafio 2]

**Oportunidades de mercado:**
- [oportunidade 1 — com dados de mercado se possível]
- [oportunidade 2]

## 1. Roadmap Financeiro
- **Investimento Inicial Estimado:** R$ [valor concreto]
- **Custos Mensais Fixos:** R$ [valor]
- **Custos Mensais Variáveis:** R$ [valor estimado]
- **Ponto de Equilíbrio:** [X] meses
- **Projeção Mês 1:** R$ [receita estimada]
- **Projeção Mês 6:** R$ [receita estimada]
- **Projeção Mês 12:** R$ [receita estimada]
- **Margem Bruta Projetada:** [%]
- **Fontes de Financiamento Recomendadas:** [opções ranqueadas por adequação ao perfil]

## 2. Estrutura Jurídica Recomendada
- **Tipo Societário:** [LTDA/MEI/SA — com justificativa]
- **CNPJ e Inscrições:** [lista do que precisa abrir]
- **Contratos Essenciais:** [lista priorizada]
- **Conformidade LGPD:** [ações concretas necessárias]
- **Proteção de Propriedade Intelectual:** [registro de marca, patentes, etc.]
- **Prazo sugerido para regularização:** [X semanas/meses]

## 3. Estratégia de Marketing e Vendas
- **Posicionamento:** [frase de impacto clara]
- **ICP (Cliente Ideal):** [perfil detalhado: setor, tamanho, dor principal, orçamento]
- **Canais Prioritários (Top 3 ranqueados):**
  1. [canal] — [razão estratégica] — [CAC estimado]
  2. [canal] — [razão estratégica] — [CAC estimado]
  3. [canal] — [razão estratégica] — [CAC estimado]
- **CAC Alvo:** R$ [valor]
- **LTV Mínimo:** R$ [valor]
- **Ratio LTV/CAC:** [X:1 — meta saudável é > 3:1]
- **Estratégia de Go-to-Market:** [fases com marcos]

## 4. Arquitetura Técnica
- **Stack Recomendada:** [tecnologias com justificativa de custo/benefício]
- **Infraestrutura:** [cloud + configurações + estimativa de custo mensal]
- **MVP — 5 Funcionalidades Essenciais:**
  1. [funcionalidade] — [esforço estimado]
  2. [funcionalidade] — [esforço estimado]
  3. [funcionalidade] — [esforço estimado]
  4. [funcionalidade] — [esforço estimado]
  5. [funcionalidade] — [esforço estimado]
- **Tempo Estimado para MVP:** [X semanas com time de Y pessoas]
- **Escalabilidade:** [plano para 10x o volume atual]

## 5. Cronograma de Execução (12 Semanas)
- **Semanas 1-2** *(Responsável: [nome/papel])*: [ações específicas com entregável]
- **Semanas 3-4** *(Responsável: [nome/papel])*: [ações específicas com entregável]
- **Semanas 5-8** *(Responsável: [nome/papel])*: [ações específicas com entregável]
- **Semanas 9-12** *(Responsável: [nome/papel])*: [ações específicas com entregável]
- **Marco 30 dias:** [entregável concreto]
- **Marco 60 dias:** [entregável concreto]
- **Marco 90 dias:** [entregável concreto]

## 6. KPIs e Métricas de Sucesso
| Métrica | Meta 30 dias | Meta 90 dias | Frequência |
|---------|-------------|-------------|------------|
| [KPI 1 — ex: MRR] | R$ [valor] | R$ [valor] | Mensal |
| [KPI 2 — ex: CAC] | R$ [valor] | R$ [valor] | Mensal |
| [KPI 3 — ex: Churn] | [%] | [%] | Mensal |
| [KPI 4 — ex: NPS] | [valor] | [valor] | Trimestral |
| [KPI 5 — ex: Conversion Rate] | [%] | [%] | Semanal |

## 7. Riscos e Planos de Contingência
| Risco | Probabilidade | Impacto | Mitigação | Contingência |
|-------|---------------|---------|-----------|-------------|
| [risco 1] | Alta/Média/Baixa | Alto/Médio/Baixo | [ação preventiva] | [plano B se acontecer] |
| [risco 2] | Alta/Média/Baixa | Alto/Médio/Baixo | [ação preventiva] | [plano B se acontecer] |
| [risco 3] | Alta/Média/Baixa | Alto/Médio/Baixo | [ação preventiva] | [plano B se acontecer] |

## 8. Checklist de Ações Imediatas (Esta Semana)
- [ ] [Ação 1] — Responsável: [quem] — Prazo: [data ou "até sexta"]
- [ ] [Ação 2] — Responsável: [quem] — Prazo: [data ou "até sexta"]
- [ ] [Ação 3] — Responsável: [quem] — Prazo: [data ou "até sexta"]
- [ ] [Ação 4] — Responsável: [quem] — Prazo: [data ou "até sexta"]
- [ ] [Ação 5] — Responsável: [quem] — Prazo: [data ou "até sexta"]

---
**Nota do Marco:** [mensagem personalizada e motivacional para o usuário, referenciando detalhes específicos da sessão]

---
Use números concretos e valores realistas para o mercado brasileiro.
Considere a realidade fiscal, trabalhista e de mercado do Brasil atual.
Seja PROFUNDO: cada especialista contribuiu com análises valiosas — sintetize-as com maestria.

TRANSCRIÇÃO DA SESSÃO:
{transcript}
"""

# ─── Prompt: Análise SWOT ──────────────────────────────────────────────────────
SWOT_PROMPT = """Você é Marco, o Estrategista-Chefe do Hive Mind.
Com base na transcrição da sessão e no contexto fornecido, gere uma Análise SWOT COMPLETA e ESTRATÉGICA para o negócio do usuário.

## FORMATO OBRIGATÓRIO (Markdown):

# Análise SWOT Estratégica — {projeto}

## Contexto do Negócio
[2 parágrafos: o que é o negócio, o mercado em que está inserido e o estágio atual]

## Matriz SWOT

### 💪 Forças (Strengths) — Fatores Internos Positivos
Liste 6-8 forças reais identificadas na sessão, com justificativa para cada uma:
- **[Força]:** [Justificativa estratégica de por que isso é uma vantagem]

### ⚠️ Fraquezas (Weaknesses) — Fatores Internos Negativos
Liste 5-7 fraquezas honestas, com plano de ação para cada:
- **[Fraqueza]:** [Impacto no negócio + como mitigar]

### 🚀 Oportunidades (Opportunities) — Fatores Externos Positivos
Liste 6-8 oportunidades de mercado (use dados pesquisados quando disponível):
- **[Oportunidade]:** [Por que existe agora e como aproveitar]

### 🔴 Ameaças (Threats) — Fatores Externos Negativos
Liste 5-7 ameaças reais do mercado/setor:
- **[Ameaça]:** [Probabilidade + plano de contingência]

## Cruzamentos Estratégicos (Matriz SO/ST/WO/WT)

### SO — Usar Forças para Aproveitar Oportunidades
- [Estratégia 1: qual força + qual oportunidade]
- [Estratégia 2]

### ST — Usar Forças para Neutralizar Ameaças
- [Estratégia 1]
- [Estratégia 2]

### WO — Superar Fraquezas Aproveitando Oportunidades
- [Estratégia 1]
- [Estratégia 2]

### WT — Minimizar Fraquezas e Evitar Ameaças
- [Estratégia 1]
- [Estratégia 2]

## Prioridades Estratégicas (Top 5)
Com base na matriz, estas são as 5 ações mais urgentes e de maior impacto:
1. [Ação prioritária com prazo sugerido]
2. [...]
3. [...]
4. [...]
5. [...]

---
**Nota do Marco:** [mensagem personalizada com insight estratégico específico para o usuário]

---
Use dados reais do mercado brasileiro quando disponível.
Contexto da sessão e dados pesquisados:
{transcript}
"""

# ─── Prompt: Business Model Canvas ────────────────────────────────────────────
CANVAS_PROMPT = """Você é Marco, o Estrategista-Chefe do Hive Mind.
Com base na sessão, gere um Business Model Canvas (BMC) COMPLETO para o negócio do usuário.

## FORMATO OBRIGATÓRIO (Markdown):

# Business Model Canvas — {projeto}

## Visão Geral
[1 parágrafo explicando o modelo de negócio em uma frase e o contexto]

---

## 🤝 Parcerias-Chave (Key Partners)
Quem são os parceiros e fornecedores essenciais:
- **[Parceiro/Categoria]:** [Papel estratégico e por que é essencial]
(mínimo 4 itens)

## ⚙️ Atividades-Chave (Key Activities)
O que a empresa DEVE fazer para entregar valor:
- **[Atividade]:** [Por que é crítica]
(mínimo 4 itens)

## 🏗️ Recursos-Chave (Key Resources)
Ativos fundamentais para o modelo funcionar:
- **[Recurso]:** [Tipo: humano/físico/intelectual/financeiro — custo estimado]
(mínimo 4 itens)

## 💎 Proposta de Valor (Value Propositions)
O que o negócio entrega de valor único ao cliente:
- **[Proposta]:** [Dor solucionada ou ganho gerado]
(mínimo 3 itens — seja específico e diferenciado)

## 💬 Relacionamento com Clientes (Customer Relationships)
Como a empresa se relaciona com cada segmento:
- **[Tipo de relacionamento]:** [Segmento afetado + como é executado]

## 📦 Canais (Channels)
Como o produto/serviço chega ao cliente:
- **[Canal]:** [Online/offline — custo/benefício — fase do funil]
(mínimo 4 itens)

## 👥 Segmentos de Clientes (Customer Segments)
Para quem o negócio cria valor:
- **[Segmento]:** [Características demográficas/psicográficas + tamanho estimado do mercado]
(mínimo 2 segmentos)

## 💰 Estrutura de Custos (Cost Structure)
Principais custos do modelo:
| Categoria | Tipo (Fixo/Variável) | Estimativa Mensal |
|-----------|---------------------|------------------|
| [custo 1] | [tipo] | R$ [valor] |
| [custo 2] | [tipo] | R$ [valor] |
| [custo 3] | [tipo] | R$ [valor] |

## 💵 Fontes de Receita (Revenue Streams)
Como o negócio ganha dinheiro:
| Fonte | Modelo | Estimativa Mensal (Yr1) |
|-------|--------|------------------------|
| [fonte 1] | [assinatura/transação/licença...] | R$ [valor] |
| [fonte 2] | [...] | R$ [valor] |

## Análise de Viabilidade do Canvas
[2 parágrafos: (1) pontos fortes do modelo, (2) pontos de atenção e melhorias sugeridas]

---
**Nota do Marco:** [insight sobre o modelo e próximo passo crítico para o usuário]

---
Contexto e dados da sessão:
{transcript}
"""

# ─── Prompt: Pitch Deck ───────────────────────────────────────────────────────
PITCH_DECK_PROMPT = """Você é Marco, o Estrategista-Chefe do Hive Mind.
Crie um Pitch Deck PROFISSIONAL em formato de documento estruturado para o negócio do usuário.
Este documento será a base para uma apresentação de 10-12 slides para investidores/parceiros.

## FORMATO OBRIGATÓRIO (Markdown):

# Pitch Deck — {projeto}
### Apresentação para {publico}

---

## Slide 1 — Capa
**Nome do Negócio:** {projeto}
**Tagline:** [Uma frase impactante de até 10 palavras que resume a proposta de valor]
**Apresentado por:** [Nome do usuário]
**Data:** [mês/ano]

---

## Slide 2 — O Problema
**Headline do Slide:** [Frase de impacto sobre o problema]

[Descreva o problema em 3 bullet points curtos e objetivos]
- 🔴 [Dor 1 — seja específico com dado ou estatística]
- 🔴 [Dor 2]
- 🔴 [Dor 3]

**Dimensão do problema:** [Quantas pessoas/empresas sofrem com isso? Qual o custo disso?]

---

## Slide 3 — A Solução
**Headline do Slide:** [Como vocês resolvem o problema]

[Descrição da solução em 2-3 linhas]

**Como funciona (3 passos simples):**
1. [Passo 1]
2. [Passo 2]
3. [Passo 3]

**Diferencial competitivo:** [O que ninguém mais faz igual]

---

## Slide 4 — Mercado (TAM / SAM / SOM)
**Mercado Total Endereçável (TAM):** R$ [valor] — [fonte ou base de cálculo]
**Mercado Acessível (SAM):** R$ [valor] — [segmento que você pode atingir]
**Mercado Alvo Inicial (SOM):** R$ [valor] — [o que você vai capturar em 12-24 meses]

**Por que agora:** [2-3 tendências de mercado que tornam este o momento certo]

---

## Slide 5 — Produto / Serviço
**MVP atual:** [O que já existe ou está sendo construído]
**Funcionalidades principais:**
- [Feature 1 — valor entregue]
- [Feature 2 — valor entregue]
- [Feature 3 — valor entregue]

**Roadmap (próximos 12 meses):**
- Q1: [Marco]
- Q2: [Marco]
- Q3: [Marco]
- Q4: [Marco]

---

## Slide 6 — Modelo de Negócio
**Como ganhamos dinheiro:**
| Fonte de Receita | Modelo de Precificação | Ticket Médio |
|-----------------|----------------------|-------------|
| [fonte 1] | [assinatura/transação/...] | R$ [valor] |
| [fonte 2] | [...] | R$ [valor] |

**Unit Economics projetados:**
- CAC: R$ [valor]
- LTV: R$ [valor]
- LTV/CAC: [ratio — meta > 3x]
- Payback period: [X meses]

---

## Slide 7 — Tração (se houver)
[Se o negócio já tem números, apresente aqui. Se não, apresente validações e indicadores de demanda]

**Indicadores de validação:**
- [Métrica 1: número real ou estimado]
- [Métrica 2]
- [Parceiros, clientes em teste, cartas de intenção, etc.]

---

## Slide 8 — Concorrência
**Análise competitiva:**
| Concorrente | Ponto Forte | Ponto Fraco | Nossa Vantagem |
|------------|-------------|-------------|----------------|
| [concorrente 1] | [...] | [...] | [...] |
| [concorrente 2] | [...] | [...] | [...] |
| [status quo atual] | [...] | [...] | [...] |

**Posicionamento:** [Por que somos diferentes — não apenas melhores]

---

## Slide 9 — Go-to-Market
**Estratégia de entrada:**
1. **Fase 1 (0-3 meses):** [Canal + meta + budget estimado]
2. **Fase 2 (3-6 meses):** [Canal + meta + budget estimado]
3. **Fase 3 (6-12 meses):** [Canal + meta + budget estimado]

**Canal principal de aquisição:** [Por que este canal e qual o CAC estimado]

---

## Slide 10 — Time
**Fundadores e Equipe-Chave:**
- **[Nome/Papel]:** [2 linhas sobre experiência e por que é a pessoa certa]
- (adicionar conforme contexto da sessão)

**O que nos falta e como vamos resolver:** [Gaps e plano de hiring]

---

## Slide 11 — Projeções Financeiras
| Métrica | Ano 1 | Ano 2 | Ano 3 |
|---------|-------|-------|-------|
| Receita | R$ [valor] | R$ [valor] | R$ [valor] |
| Custo Total | R$ [valor] | R$ [valor] | R$ [valor] |
| Lucro/Prejuízo | R$ [valor] | R$ [valor] | R$ [valor] |
| Clientes Ativos | [nº] | [nº] | [nº] |
| MRR | R$ [valor] | R$ [valor] | R$ [valor] |

**Premissas principais:** [Base das projeções]

---

## Slide 12 — O Pedido (The Ask)
**Rodada:** [Seed / Pré-seed / Série A]
**Valor buscado:** R$ [valor]
**Uso dos recursos:**
| Destino | % | Valor |
|---------|---|-------|
| [Produto/Tech] | [%] | R$ [valor] |
| [Marketing/Growth] | [%] | R$ [valor] |
| [Operações/Time] | [%] | R$ [valor] |

**O que entregamos em 18 meses:** [Marcos que justificam o investimento]
**Contato:** [Email/LinkedIn]

---

**Nota do Marco:** [Conselho estratégico sobre como apresentar este pitch]

---
Contexto e dados da sessão:
{transcript}
"""

# ─── Prompt: Proposta Comercial ───────────────────────────────────────────────
PROPOSTA_COMERCIAL_PROMPT = """Você é Marco, o Estrategista-Chefe do Hive Mind.
Com base na sessão, crie uma Proposta Comercial PROFISSIONAL e PERSUASIVA.

## FORMATO OBRIGATÓRIO (Markdown):

# Proposta Comercial
## {projeto}

**Para:** [Nome do cliente/empresa potencial, se mencionado, ou "A quem possa interessar"]
**De:** [Nome do usuário/empresa]
**Data:** [data atual]
**Validade:** 30 dias

---

## 1. Entendimento do Contexto
[2 parágrafos mostrando que você entendeu a dor do cliente. Use linguagem empática e técnica.]

**Principais desafios identificados:**
- [Desafio 1 do cliente]
- [Desafio 2 do cliente]
- [Desafio 3 do cliente]

---

## 2. Nossa Solução Proposta
[Descrição clara e objetiva do que será entregue]

**O que entregaremos:**
| Entregável | Descrição | Prazo |
|-----------|-----------|-------|
| [item 1] | [descrição] | [prazo] |
| [item 2] | [descrição] | [prazo] |
| [item 3] | [descrição] | [prazo] |

---

## 3. Nossa Metodologia
**Como trabalhamos:**
1. **[Fase 1 — Nome]:** [O que acontece + resultado esperado]
2. **[Fase 2 — Nome]:** [O que acontece + resultado esperado]
3. **[Fase 3 — Nome]:** [O que acontece + resultado esperado]

---

## 4. Por Que Nós?
**Nossos diferenciais:**
- ✅ [Diferencial 1 com prova ou evidência]
- ✅ [Diferencial 2 com prova ou evidência]
- ✅ [Diferencial 3 com prova ou evidência]

---

## 5. Investimento
| Serviço/Produto | Valor |
|----------------|-------|
| [item 1] | R$ [valor] |
| [item 2] | R$ [valor] |
| **Total** | **R$ [valor]** |

**Condições de pagamento:**
- [Opção 1: à vista com desconto X%]
- [Opção 2: parcelado em X vezes]

**Incluso:**
- [O que está incluído]

**Não incluso:**
- [O que não está incluído — seja transparente]

---

## 6. Garantias e SLA
- **Prazo de entrega:** [X dias/semanas após assinatura]
- **Revisões incluídas:** [número de rodadas]
- **Suporte pós-entrega:** [X dias/meses]
- **Política de reembolso:** [condições]

---

## 7. Próximos Passos
Para avançar com esta proposta:
1. [Passo 1: aprovação/reunião de alinhamento]
2. [Passo 2: assinatura do contrato]
3. [Passo 3: início do projeto]

**Prazo para resposta:** Esta proposta é válida até [data — 30 dias da emissão].

---

## 8. Termos Gerais
[Cláusulas básicas de confidencialidade, propriedade intelectual e condições gerais]

---

**Note de Marco:** [Dica estratégica para fechar a proposta com sucesso]

---
Contexto da sessão:
{transcript}
"""

# ─── Prompt: Modelo de Contrato ───────────────────────────────────────────────
MODELO_CONTRATO_PROMPT = """Você é Marco, Estrategista-Chefe do Hive Mind.
Gere um modelo de contrato COMPLETO mas com linguagem acessível, adaptado ao contexto da sessão.

## INSTRUÇÕES:
- Este é um MODELO BASE — recomende sempre revisão por advogado antes de assinar
- Use linguagem clara mas juridicamente consistente com o direito brasileiro
- Adapte ao tipo de contrato solicitado: {tipo_contrato}
- Partes envolvidas: {partes}

## FORMATO OBRIGATÓRIO (Markdown):

# CONTRATO DE {tipo_contrato_upper}

> ⚠️ **AVISO IMPORTANTE:** Este é um modelo base gerado como ponto de partida. Recomendamos fortemente a revisão por um advogado especializado antes da assinatura. O Hive Mind e o agente Marco não são responsáveis pelo uso deste modelo sem revisão jurídica.

---

**CONTRATANTE:** [Nome completo / Razão Social], [CPF/CNPJ], com sede/residência em [endereço], doravante denominado simplesmente "CONTRATANTE".

**CONTRATADO(A):** [Nome completo / Razão Social], [CPF/CNPJ], com sede/residência em [endereço], doravante denominado simplesmente "CONTRATADO".

---

## CLÁUSULA 1ª — DO OBJETO
[Descrição detalhada do que é contratado, com especificações claras do serviço/produto/parceria]

## CLÁUSULA 2ª — DO PRAZO
**2.1** O presente contrato terá vigência de [prazo], com início em [data de início] e término em [data de término].
**2.2** [Cláusula de renovação automática ou não]
**2.3** [Condições para prorrogação]

## CLÁUSULA 3ª — DO VALOR E FORMA DE PAGAMENTO
**3.1** Pela execução dos serviços/fornecimento descrito na Cláusula 1ª, o CONTRATANTE pagará ao CONTRATADO o valor de R$ [valor] ([valor por extenso]).
**3.2** O pagamento será realizado da seguinte forma: [condições de pagamento].
**3.3** Em caso de atraso no pagamento, incidirá multa de [X]% sobre o valor devido, além de juros de [Y]% ao mês.

## CLÁUSULA 4ª — DAS OBRIGAÇÕES DO CONTRATADO
O CONTRATADO obriga-se a:
**4.1** [Obrigação 1]
**4.2** [Obrigação 2]
**4.3** [Obrigação 3]
**4.4** Manter sigilo sobre todas as informações confidenciais do CONTRATANTE.

## CLÁUSULA 5ª — DAS OBRIGAÇÕES DO CONTRATANTE
O CONTRATANTE obriga-se a:
**5.1** Efetuar os pagamentos nas datas acordadas.
**5.2** Fornecer todas as informações e materiais necessários para a execução dos serviços.
**5.3** [Outras obrigações específicas]

## CLÁUSULA 6ª — DA CONFIDENCIALIDADE E SIGILO
**6.1** As partes comprometem-se a manter sigilo sobre todas as informações confidenciais trocadas em função deste contrato.
**6.2** A obrigação de confidencialidade perdurará por [X] anos após a extinção do contrato.
**6.3** Excluem-se do sigilo as informações que: (i) já eram de conhecimento público; (ii) se tornarem públicas sem culpa das partes; (iii) precisarem ser divulgadas por ordem judicial.

## CLÁUSULA 7ª — DA PROPRIEDADE INTELECTUAL
**7.1** [Definir claramente a quem pertence a propriedade intelectual gerada durante o contrato]
**7.2** [Licenças concedidas, se houver]

## CLÁUSULA 8ª — DA RESCISÃO
**8.1** O presente contrato poderá ser rescindido:
   - a) Por acordo mútuo entre as partes, mediante notificação prévia de [X] dias;
   - b) Por descumprimento de qualquer cláusula, mediante notificação prévia de [X] dias;
   - c) Imediatamente em caso de [situações específicas].
**8.2** Em caso de rescisão antecipada sem justa causa pelo CONTRATANTE, aplicar-se-á multa de [X]% sobre o valor total do contrato.

## CLÁUSULA 9ª — DAS PENALIDADES
**9.1** O descumprimento de qualquer cláusula deste contrato sujeitará a parte infratora ao pagamento de multa de R$ [valor] ou [X]% do valor contratual, sem prejuízo das demais cominações legais.

## CLÁUSULA 10ª — DAS DISPOSIÇÕES GERAIS
**10.1** O presente contrato representa o acordo integral entre as partes, substituindo quaisquer entendimentos anteriores.
**10.2** Qualquer alteração deverá ser feita por escrito e assinada por ambas as partes.
**10.3** A invalidade de qualquer cláusula não invalida as demais.

## CLÁUSULA 11ª — DO FORO
As partes elegem o Foro da Comarca de [cidade], Estado de [estado], para dirimir quaisquer controvérsias oriundas deste contrato, com renúncia expressa a qualquer outro, por mais privilegiado que seja.

---

E por estarem assim justos e contratados, assinam o presente instrumento em 2 (duas) vias de igual teor e forma, na presença de 2 (duas) testemunhas.

[Cidade], [data por extenso].

---

**CONTRATANTE:**
_________________________________
[Nome completo]
[CPF/CNPJ]

**CONTRATADO:**
_________________________________
[Nome completo]
[CPF/CNPJ]

**Testemunha 1:**
_________________________________
Nome: ___________________________
CPF: ____________________________

**Testemunha 2:**
_________________________________
Nome: ___________________________
CPF: ____________________________

---
> 💡 **Dica do Marco:** Antes de assinar, certifique-se de que: (1) todos os campos em [colchetes] foram preenchidos, (2) um advogado revisou o contrato, (3) ambas as partes receberam uma via original assinada.

---
Contexto da sessão:
{transcript}
"""

# ─── Prompt: Pesquisa de Mercado ──────────────────────────────────────────────
PESQUISA_MERCADO_PROMPT = """Você é Marco, o Estrategista-Chefe do Hive Mind, e também um analista de mercado sênior.
Com base na sessão e nos dados pesquisados (fornecidos abaixo), gere um Relatório de Pesquisa de Mercado PROFUNDO para o setor do usuário.

## FORMATO OBRIGATÓRIO (Markdown):

# Pesquisa de Mercado — {setor}
### Relatório Estratégico para {projeto}

**Data:** [data atual]
**Analista:** Marco — Estrategista-Chefe, Hive Mind

---

## Sumário Executivo
[3 parágrafos: (1) visão geral do mercado, (2) principais tendências e oportunidades, (3) recomendação estratégica central]

---

## 1. Dimensionamento do Mercado

### Mercado Global
- **Tamanho atual:** [valor em USD/EUR — com fonte]
- **Projeção para [ano+3]:** [valor]
- **CAGR:** [%] ao ano
- **Principais países:** [Top 3 com % do mercado]

### Mercado Brasileiro
- **Tamanho atual:** R$ [valor] ou US$ [valor]
- **Crescimento anual:** [%]
- **Participação no mercado global:** [%]
- **Tendência:** [crescente/estável/em declínio — justificativa]

---

## 2. Análise do Setor

### Drivers de Crescimento
- **[Driver 1]:** [Como está impulsionando o mercado]
- **[Driver 2]:** [Como está impulsionando o mercado]
- **[Driver 3]:** [Como está impulsionando o mercado]

### Barreiras de Entrada
| Barreira | Nível (Alto/Médio/Baixo) | Como Superar |
|---------|--------------------------|-------------|
| [barreira 1] | [nível] | [estratégia] |
| [barreira 2] | [nível] | [estratégia] |
| [barreira 3] | [nível] | [estratégia] |

### Regulação e Compliance
[Principais normas, regulamentações e exigências legais do setor no Brasil]

---

## 3. Análise Competitiva

### Principais Players do Mercado
| Empresa | Posicionamento | Modelo | Market Share Est. | Ponto Fraco |
|---------|---------------|--------|------------------|-------------|
| [empresa 1] | [posição] | [modelo] | [%] | [fraqueza] |
| [empresa 2] | [...] | [...] | [%] | [...] |
| [empresa 3] | [...] | [...] | [%] | [...] |

### Gaps de Mercado (Oportunidades Não Aproveitadas)
- **[Gap 1]:** [Descrição + tamanho da oportunidade]
- **[Gap 2]:** [Descrição + tamanho da oportunidade]
- **[Gap 3]:** [Descrição + tamanho da oportunidade]

---

## 4. Perfil do Consumidor / Cliente

### Segmentação Primária
[Quem compra, por que compra, quando compra, quanto paga]

### ICP — Ideal Customer Profile
- **Perfil B2C:** [Se aplicável — demografia, psicografia, comportamento de compra]
- **Perfil B2B:** [Se aplicável — porte da empresa, setor, cargo decisor, orçamento típico]

### Jornada de Compra
1. **Consciência:** [Como o cliente descobre a necessidade]
2. **Consideração:** [Como avalia opções]
3. **Decisão:** [Fatores decisivos de compra]
4. **Retenção:** [O que gera lealdade]

---

## 5. Tendências e Inovações

### Macro Tendências (3-5 anos)
- **[Tendência 1]:** [Impacto no setor e oportunidade gerada]
- **[Tendência 2]:** [Impacto no setor e oportunidade gerada]
- **[Tendência 3]:** [Impacto no setor e oportunidade gerada]

### Tecnologias Emergentes
- **[Tecnologia]:** [Como está mudando o setor e prazo de adoção]

---

## 6. Análise PESTEL

| Fator | Impacto | Oportunidade/Ameaça |
|-------|---------|---------------------|
| **P**olítico | [análise] | [O/A] |
| **E**conômico | [análise] | [O/A] |
| **S**ocial | [análise] | [O/A] |
| **T**ecnológico | [análise] | [O/A] |
| **E**cológico | [análise] | [O/A] |
| **L**egal | [análise] | [O/A] |

---

## 7. Recomendações Estratégicas

### Posicionamento Recomendado
[Como o negócio do usuário deve se posicionar neste mercado]

### Janela de Oportunidade
[Por que agora é o momento certo e por quanto tempo essa janela permanece aberta]

### Top 5 Ações Baseadas na Pesquisa
1. [Ação com fundamentação nos dados]
2. [...]
3. [...]
4. [...]
5. [...]

---

## 8. Fontes e Referências
[Liste as fontes consultadas, mesmo que sejam estimativas baseadas em conhecimento do setor]

---
**Nota do Marco:** [Insight exclusivo com base nos dados cruzados desta pesquisa]

---
Dados pesquisados e contexto da sessão:
{transcript}
"""

# ─── Prompt: Orientação para Órgãos Públicos ──────────────────────────────────
ORIENTACAO_ORGAO_PROMPT = """Você é Marco, Estrategista-Chefe do Hive Mind e especialista em burocracia empresarial brasileira.
Com base no processo solicitado ({orgao_processo}), gere um guia PRÁTICO, DETALHADO e ATUALIZADO para o usuário.

## INSTRUÇÕES CRÍTICAS:
- NÃO gere o documento oficial — o usuário deve fazê-lo na plataforma governamental
- Seja MUITO específico: listando passos exatos, links, prazos e custos
- Considere a realidade burocrática atual do Brasil (2024-2025)
- SE HOUVER VARIAÇÃO POR ESTADO/MUNICÍPIO, sinalize claramente
- Sempre inclua dicas práticas que economizem tempo e dinheiro

## FORMATO OBRIGATÓRIO (Markdown):

# Guia Prático: {orgao_processo}
### Para: {projeto} — {user_name}

> 📌 **Importante:** Este guia orienta o processo. O(s) documento(s) oficial(is) deve(m) ser gerado(s) diretamente na plataforma governamental indicada. O Hive Mind fornece orientação estratégica, não substitui assessoria jurídica ou contábil especializada.

---

## O que é e Para que Serve
[2 parágrafos explicando o processo, sua importância e quando é necessário]

---

## Pré-Requisitos
Antes de iniciar, certifique-se de ter:
- [ ] [Documento/Requisito 1]
- [ ] [Documento/Requisito 2]
- [ ] [Documento/Requisito 3]
(adicione todos os pré-requisitos relevantes)

---

## Passo a Passo Detalhado

### Passo 1 — [Nome do passo]
**Onde fazer:** [Plataforma/Link oficial]
**O que fazer:** [Descrição detalhada das ações]
**Prazo:** [Tempo estimado para concluir este passo]
**Custo:** R$ [valor] ou Gratuito
**Dica:** [Dica prática para facilitar ou acelerar]

### Passo 2 — [Nome do passo]
**Onde fazer:** [...]
**O que fazer:** [...]
**Prazo:** [...]
**Custo:** R$ [...]
**Dica:** [...]

(adicione todos os passos necessários)

---

## Custos Totais Estimados

| Item | Custo | Observação |
|------|-------|------------|
| [taxa 1] | R$ [valor] | [quando pagar] |
| [taxa 2] | R$ [valor] | [quando pagar] |
| **Total Estimado** | **R$ [total]** | [variações possíveis] |

> 💡 Estes valores são estimativas. Verifique sempre os valores atuais nos portais oficiais.

---

## Prazo Total Esperado
**Tempo mínimo:** [X dias/semanas]
**Tempo médio:** [Y dias/semanas]
**Fatores que podem atrasar:** [liste os principais gargalos]

---

## Links Oficiais Relevantes

| Recurso | Link | O que encontrar |
|---------|------|----------------|
| [Portal principal] | [URL] | [o que acessar] |
| [Portal 2] | [URL] | [o que acessar] |
| [Portal 3] | [URL] | [o que acessar] |

---

## Erros Comuns a Evitar
- ❌ **[Erro 1]:** [Por que acontece e como evitar]
- ❌ **[Erro 2]:** [Por que acontece e como evitar]
- ❌ **[Erro 3]:** [Por que acontece e como evitar]

---

## Dicas de Profissionais para Facilitar o Processo
- 💡 [Dica 1 — que economize tempo ou dinheiro]
- 💡 [Dica 2]
- 💡 [Dica 3]
- 💡 [Dica 4]

---

## Quando Contratar um Profissional
[Oriente quando vale a pena contratar contador, advogado ou despachante para este processo]
**Custo aproximado de terceirizar:** R$ [faixa de preço]
**Benefício:** [O que o profissional adiciona]

---

**Nota do Marco:** [Conselho estratégico específico para o contexto do usuário]

---
Contexto da sessão:
{transcript}
"""

# ─── Mapeamento: doc_type → (prompt, título_padrão) ──────────────────────────
DOCUMENT_PROMPTS: dict[str, tuple[str, str]] = {
    "execution_plan":        (SUMMARIZATION_PROMPT,       "Plano de Execução Estratégico"),
    "swot":                  (SWOT_PROMPT,                "Análise SWOT Estratégica"),
    "canvas":                (CANVAS_PROMPT,              "Business Model Canvas"),
    "pitch_deck":            (PITCH_DECK_PROMPT,          "Pitch Deck"),
    "proposta_comercial":    (PROPOSTA_COMERCIAL_PROMPT,  "Proposta Comercial"),
    "modelo_contrato":       (MODELO_CONTRATO_PROMPT,     "Modelo de Contrato"),
    "pesquisa_mercado":      (PESQUISA_MERCADO_PROMPT,    "Pesquisa de Mercado"),
    "orientacao_orgao":      (ORIENTACAO_ORGAO_PROMPT,    "Guia de Processo Público"),
}




def _draw_header_footer(canvas, doc, project_name: str, user_name: str):
    """Desenha cabeçalho Gold e rodapé discreto em cada página."""
    canvas.saveState()

    # ── Fundo do cabeçalho ──────────────────────────────────────────────────
    canvas.setFillColor(DARK_BG)
    canvas.rect(0, PAGE_H - 18 * mm, PAGE_W, 18 * mm, fill=1, stroke=0)

    # Linha dourada no cabeçalho
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.5)
    canvas.line(MARGIN_X, PAGE_H - 18 * mm, PAGE_W - MARGIN_X, PAGE_H - 18 * mm)

    # Injeção Vetorial do Logo (Hive Mind)
    import re
    logo_path_d = (
        "M479.5 557 C481.88 555.3 484 554.82 484 551.5 C484 551.03 483.08 550.96 483 550.5 C482.07 545.21 482.05 539.77 481 534.5 C478.57 522.36 476.29 528.64 478 515.5 C478.09 514.8 478.8 514.13 479.5 514 C483.45 513.27 487.56 513.79 491.5 513 C494.29 512.44 497.04 511.43 499.5 510 C503.42 507.73 507.02 504.9 510.5 502 C513.04 499.89 514.99 497.14 517.5 495 C524.17 489.3 531.8 484.7 538 478.5 C540.75 475.75 542.37 472.03 544 468.5 C544.42 467.59 543.76 466.47 544 465.5 C544.44 463.76 545.85 462.29 546 460.5 C546.53 454.19 543.94 447.49 546 441.5 C547.85 436.13 553.73 433.14 557 428.5 C560.09 424.1 562.71 419.36 565 414.5 C565.43 413.6 564.76 412.47 565 411.5 C565.44 409.76 566.82 408.29 567 406.5 C567.5 401.52 567.31 396.49 567 391.5 C566.97 391.03 566.08 390.96 566 390.5 C565.73 388.86 566.45 387.11 566 385.5 C561.48 369.23 561.34 374.28 551 360.5 C550.11 359.31 549.41 357.93 549 356.5 C548.73 355.54 549.24 354.47 549 353.5 C548.89 353.04 548.03 352.97 548 352.5 C547.69 348.18 548.31 343.82 548 339.5 C547.97 339.03 547.08 338.96 547 338.5 C545.09 328.02 548.33 327.44 540 318.5 C533.57 311.59 525.53 306.32 519 299.5 C517.76 298.2 517.4 296.25 517 294.5 C516.4 291.88 516.8 289.07 516 286.5 C515.11 283.65 513.67 280.97 512 278.5 C508.48 273.31 503.98 269.04 498.5 266 C497.92 265.68 497.11 266.26 496.5 266 C494.71 265.23 493.37 263.53 491.5 263 C482.46 260.42 483.19 264.28 475.5 259 C468.7 254.32 465.45 248.09 457.5 245 C454.69 243.91 451.46 244.59 448.5 244 C448.04 243.91 447.97 243 447.5 243 C444.15 243 440.77 243.26 437.5 244 C428.49 246.05 423.45 248.05 417 254.5 C410.28 261.22 409.9 267.94 408 276.5 C407.9 276.96 407.08 277.04 407 277.5 C406.73 279.14 407.27 280.86 407 282.5 C406.92 282.96 406.04 283.03 406 283.5 C405.36 290.81 405.78 298.2 405 305.5 C404.84 306.98 402.5 307.46 401.5 307 C397.71 305.25 393.99 303.29 390.5 301 C388.13 299.44 385.6 297.84 384 295.5 C383.25 294.4 384.26 292.81 384 291.5 C383.91 291.04 383.03 290.97 383 290.5 C382.69 285.18 383.31 279.82 383 274.5 C382.97 274.03 382.06 273.97 382 273.5 C381.71 271.18 382.26 268.82 382 266.5 C381.92 265.76 381.61 264.92 381 264.5 C373.03 259.03 364.81 253.94 356.5 249 C353.3 247.1 350.06 245.11 346.5 244 C344.59 243.4 342.36 243.26 340.5 244 C333.85 246.66 327.75 250.51 321.5 254 C316.41 256.84 311.37 259.8 306.5 263 C305.52 263.65 304.09 264.32 304 265.5 C303.23 275.47 305.04 285.55 304 295.5 C303.83 297.14 301.93 298.18 300.5 299 C294.04 302.71 287.04 305.43 280.5 309 C279.67 309.45 279.32 310.54 278.5 311 C276.28 312.23 273.7 312.73 271.5 314 C270.48 314.59 269.1 315.33 269 316.5 C267.91 329.12 269.63 341.93 268 354.5 C267.73 356.6 265.19 357.72 263.5 359 C261 360.9 258.29 362.54 255.5 364 C251.27 366.21 246.57 367.52 242.5 370 C239.68 371.72 236.9 373.79 235 376.5 C233.6 378.48 233.24 381.09 233 383.5 C232.57 387.81 232.69 392.18 233 396.5 C233.03 396.97 233.97 397.03 234 397.5 C234.31 401.82 234.27 406.18 234 410.5 C233.93 411.55 233 412.45 233 413.5 C233 413.97 233.89 414.04 234 414.5 C234.24 415.47 233.47 416.65 234 417.5 C235.74 420.31 237.81 423.07 240.5 425 C248.58 430.81 258.25 434.27 266 440.5 C267.3 441.54 265.73 443.86 266 445.5 C266.08 445.96 266.98 446.03 267 446.5 C267.32 453.49 266.68 460.51 267 467.5 C267.02 467.97 267.95 468.03 268 468.5 C268.3 471.49 267.73 474.51 268 477.5 C268.33 481.1 272.23 481.62 274.5 483 C281.29 487.13 287.66 491.95 294.5 496 C296.68 497.29 299.27 497.78 301.5 499 C304.32 500.54 305.63 503.81 309.5 502 C318.42 497.84 326.95 492.88 335.5 488 C336.32 487.53 336.61 486.3 337.5 486 C339.74 485.25 342.29 484.18 344.5 485 C351.63 487.64 357.95 492.13 364.5 496 C365.31 496.48 365.69 497.51 366.5 498 C369.06 499.53 371.67 501.06 374.5 502 C375.76 502.42 377.24 502.44 378.5 502 C399.49 494.59 384.04 497.83 404.5 487 C405.68 486.38 407.56 486.06 408.5 487 C411.74 490.24 413.06 494.99 416 498.5 C421.6 505.19 428.48 510.75 434 517.5 C437.51 521.79 440.23 526.69 443 531.5 C445.23 535.37 447.3 539.36 449 543.5 C451.23 548.92 450.8 555.11 458.5 556 C465.46 556.8 472.5 556.67 479.5 557 Z "
        "M442.5 372 C437.17 368.33 431.56 365.03 426.5 361 C423.36 358.5 419.36 356.27 418 352.5 C416.3 347.8 418.31 342.49 418 337.5 C417.97 337.03 417.04 336.97 417 336.5 C416.69 332.51 416.69 328.49 417 324.5 C417.04 324.03 417.97 323.97 418 323.5 C418.31 319.18 418.31 314.82 418 310.5 C417.97 310.03 417 309.97 417 309.5 C417 299.83 417.36 290.15 418 280.5 C418.03 280.03 418.92 279.96 419 279.5 C419.6 276.2 419.14 272.74 420 269.5 C420.5 267.62 421.78 266.01 423 264.5 C424.63 262.48 426.33 260.42 428.5 259 C431.25 257.2 434.27 255.56 437.5 255 C442.1 254.2 446.91 254.17 451.5 255 C457.24 256.04 462.53 261.34 466 265.5 C467.39 267.17 467.87 269.56 469.5 271 C470.85 272.19 472.72 272.79 474.5 273 C490.05 274.83 483.34 269.5 497.5 278 C498.33 278.5 498.31 279.81 499 280.5 C504.4 285.9 502.07 280.66 505 287.5 C505.42 288.47 505.9 289.45 506 290.5 C506.24 293.16 506.95 296.01 506 298.5 C504.99 301.15 502.84 303.39 500.5 305 C495.22 308.64 489.07 310.82 483.5 314 C482.05 314.83 480.68 315.82 479.5 317 C477.83 318.67 476.29 320.51 475 322.5 C474.43 323.38 474 324.45 474 325.5 C474 335.17 476.01 344.88 475 354.5 C474.78 356.61 472.24 357.79 470.5 359 C465.71 362.32 460.58 365.13 455.5 368 C452.9 369.47 450.35 371.12 447.5 372 C445.91 372.49 444.17 372 442.5 372 Z "
        "M314 271.5 C318.83 268.33 323.48 264.86 328.5 262 C335.58 257.97 341.29 254.64 349.5 258 C356.75 260.97 363.36 265.33 370 269.5 C370.63 269.9 370.97 270.76 371 271.5 C371.31 279.16 371.97 286.89 371 294.5 C370.76 296.39 369.04 297.89 367.5 299 C361.8 303.11 355.64 306.56 349.5 310 C347.29 311.24 344.99 312.5 342.5 313 C341.47 313.21 340.41 312.53 339.5 312 C332.39 307.85 325.2 303.79 318.5 299 C316.95 297.9 315.31 296.38 315 294.5 C313.76 286.93 314.33 279.17 314 271.5 Z "
        "M443.5 349 C444.83 349 446.37 349.7 447.5 349 C450.11 347.39 452.1 344.9 454 342.5 C454.65 341.67 454.94 340.55 455 339.5 C455.79 326.09 452.39 325.77 460 314.5 C461.98 311.57 464.69 309.14 467.5 307 C471.73 303.78 477.41 302.42 481 298.5 C481.97 297.44 479.93 294.95 478.5 295 C474.6 295.14 471.04 297.35 467.5 299 C465.99 299.7 464.73 300.88 463.5 302 C460.89 304.38 458.25 306.77 456 309.5 C453.6 312.4 454.6 316.15 449.5 317 C448.54 317.16 448.02 315.47 448 314.5 C447.35 289.23 448.5 305.58 455 283.5 C455.95 280.27 450.31 276 447.5 276 C441.99 276 439.98 276.2 437 280.5 C435.48 282.7 435.86 285.22 437 287.5 C438.07 289.65 440.75 291.11 441 293.5 C442.12 304.11 442.47 314.94 441 325.5 C440.42 329.64 436.55 332.62 435 336.5 C434.46 337.85 434.71 341.21 436 342.5 C438.34 344.84 441 346.83 443.5 349 Z "
        "M280 323.5 C286.17 319.33 292.18 314.93 298.5 311 C301.03 309.42 303.67 307.94 306.5 307 C307.76 306.58 309.24 306.58 310.5 307 C313.33 307.94 315.97 309.42 318.5 311 C343.19 326.37 338.15 318.36 337 349.5 C336.98 349.97 336.08 350.04 336 350.5 C335.18 355.44 337.76 355.2 333.5 358 C328.63 361.2 323.62 364.21 318.5 367 C314.63 369.11 310.12 371.32 305.5 370 C302.63 369.18 300.04 367.55 297.5 366 C294.03 363.88 290.97 361.13 287.5 359 C285.35 357.68 281.47 358.44 281 354.5 C279.98 345.89 281.32 337.16 281 328.5 C280.98 328.03 280.09 327.96 280 327.5 C279.74 326.19 280 324.83 280 323.5 Z "
        "M379.5 372 C374.84 372 375.77 372.6 371.5 370 C365.1 366.11 358.67 362.25 352.5 358 C351.14 357.06 349.17 356.14 349 354.5 C347.96 344.55 348.69 334.5 349 324.5 C349.04 323.1 351.82 320.41 352.5 320 C359.02 316.09 365.95 312.87 372.5 309 C375.41 307.28 374.03 304.42 379.5 307 C383.85 309.05 387.36 312.55 391.5 315 C394.71 316.9 398.38 317.96 401.5 320 C403.27 321.16 405.63 322.41 406 324.5 C407.22 331.39 406.32 338.51 406 345.5 C405.98 345.97 405.06 346.03 405 346.5 C404.01 354.43 407.71 354.04 399.5 360 C393.21 364.57 386.17 368 379.5 372 Z "
        "M463.5 543 C462 541.17 460.21 539.54 459 537.5 C455.35 531.34 452.84 524.54 449 518.5 C445.81 513.49 442.02 508.87 438 504.5 C434.33 500.51 429.63 497.53 426 493.5 C423.59 490.82 420.87 488 420 484.5 C418.46 478.35 419.63 471.81 419 465.5 C418.95 465.03 418.02 464.97 418 464.5 C417.68 457.17 415.75 449.48 418 442.5 C419.24 438.66 424.13 437.22 427.5 435 C431.99 432.04 436.53 429.04 441.5 427 C443.99 425.98 446.82 425.78 449.5 426 C452.62 426.26 458.69 430.7 457 434.5 C456.02 436.7 454.55 438.66 453 440.5 C451.03 442.85 448.96 445.18 446.5 447 C437.5 453.65 444.39 441.33 435 456.5 C434.47 457.35 434.62 458.58 435 459.5 C437.08 464.56 439.25 466.43 444.5 468 C449.87 469.61 455.68 464.91 456 459.5 C456.27 454.84 455.27 450.11 456 445.5 C457 439.19 469.92 431.26 473 440.5 C474.06 443.68 474 447.15 474 450.5 C474 450.97 473.02 451.03 473 451.5 C472.68 458.49 473.47 465.52 473 472.5 C472.95 473.21 472.11 473.64 471.5 474 C463.92 478.49 456.43 483.18 448.5 487 C447.3 487.58 445.76 487.45 444.5 487 C440.99 485.75 438.01 483.25 434.5 482 C433.24 481.55 431.79 481.65 430.5 482 C428.3 482.6 428.87 484.37 430 485.5 C434 489.5 437.69 494.01 442.5 497 C444.2 498.06 446.58 497.55 448.5 497 C451.37 496.18 453.73 494.11 456.5 493 C457.12 492.75 457.89 493.27 458.5 493 C464.62 490.25 470.79 487.52 476.5 484 C484.65 478.97 481.38 477.41 483 468.5 C483.08 468.04 483.98 467.97 484 467.5 C484.32 458.84 484.52 450.15 484 441.5 C483.85 439.08 483.53 436.38 482 434.5 C479.01 430.82 473.8 429.32 471 425.5 C469.82 423.89 470.25 421.35 471 419.5 C472.17 416.63 474.07 413.92 476.5 412 C477.55 411.17 479.32 411.38 480.5 412 C482.37 412.99 483.88 414.7 485 416.5 C489.42 423.59 493.26 431.03 497 438.5 C497.3 439.1 496.77 439.88 497 440.5 C502.84 456.08 498.25 433.21 500 459.5 C500.05 460.24 500.47 460.97 501 461.5 C503.27 463.77 506.71 466.97 510.5 465 C513.44 463.47 515.66 460.84 518 458.5 C518.53 457.97 519 457.25 519 456.5 C519 448.09 517.8 451.4 511.5 446 C505.46 440.82 502.6 437.45 499 430.5 C495.44 423.61 491.88 416.7 489 409.5 C488.5 408.26 488.52 406.74 489 405.5 C490.53 401.52 492.49 403.6 495.5 403 C497.57 402.59 499.41 401.3 501.5 401 C504.14 400.62 506.85 400.71 509.5 401 C509.97 401.05 510.04 401.92 510.5 402 C514.13 402.61 517.94 402.06 521.5 403 C524.38 403.76 526.59 406.33 529.5 407 C531.16 407.38 533 406.8 534.5 406 C536.36 405.01 539 401.98 539 399.5 C539 395.28 537.81 392.59 533.5 391 C531.94 390.42 530.1 390.54 528.5 391 C525.34 391.9 522.66 394.1 519.5 395 C517.9 395.46 516.14 394.73 514.5 395 C514.04 395.08 513.97 396 513.5 396 C507.16 396 500.73 396.19 494.5 395 C492.63 394.64 490.37 393.36 490 391.5 C489.4 388.49 490.75 385.31 492 382.5 C506.58 349.7 496.39 378.56 518 347.5 C520.91 343.32 517.01 340.06 514.5 338 C513.92 337.53 513.24 337.09 512.5 337 C507.33 336.35 505.48 336.39 502 340.5 C501.32 341.3 501.09 342.45 501 343.5 C500.26 352.33 502.47 351.25 499 358.5 C496.23 364.28 493.15 369.92 490 375.5 C487.95 379.13 484.04 384.69 480.5 387 C473.54 391.54 474.15 385.39 469 394.5 C465.84 400.09 468.9 400.55 470 405.5 C470.42 407.39 470.09 410.74 469 412.5 C467.37 415.14 465.69 417.81 463.5 420 C462.75 420.75 461.47 421.42 460.5 421 C457.65 419.78 455.08 417.8 453 415.5 C449.72 411.87 451.6 408.7 451 404.5 C450.93 404.03 450.02 403.97 450 403.5 C449.68 396.84 449.02 390.09 450 383.5 C450.24 381.87 452.08 380.84 453.5 380 C460.3 375.98 467.61 372.86 474.5 369 C475.95 368.19 477.32 367.18 478.5 366 C480.51 363.99 482.4 361.84 484 359.5 C484.6 358.63 485 357.55 485 356.5 C485 348.49 484 340.51 484 332.5 C484 332.03 484.92 331.96 485 331.5 C485.27 329.86 484.76 328.15 485 326.5 C485.11 325.76 485.44 324.99 486 324.5 C487.99 322.77 490.2 321.29 492.5 320 C497.05 317.45 501.57 314.71 506.5 313 C509.35 312.01 512.55 311.35 515.5 312 C521.74 313.39 528.91 320.43 532 325.5 C534.26 329.2 535.84 333.32 537 337.5 C537.54 339.43 536.72 341.52 537 343.5 C537.07 343.97 538.04 344.03 538 344.5 C536.78 360.31 537.72 354.6 525.5 364 C521.39 367.17 520.61 370.89 525.5 374 C526.06 374.36 526.92 374.32 527.5 374 C530.01 372.61 531.84 370.06 534.5 369 C541.68 366.13 545.53 368.04 550 374.5 C552.72 378.42 555.15 382.8 556 387.5 C557.19 394.06 556.69 400.87 556 407.5 C555.67 410.65 554.25 413.59 553 416.5 C552.23 418.29 551.33 420.08 550 421.5 C546.45 425.29 543.69 431.91 538.5 432 C531.34 432.12 526.06 424.85 519.5 422 C518.28 421.47 516.79 421.65 515.5 422 C514.08 422.39 513.48 424.29 514 425.5 C514.77 427.29 515.7 429.05 517 430.5 C518.58 432.27 520.51 433.71 522.5 435 C523.38 435.57 524.69 435.33 525.5 436 C528.59 438.55 531.45 441.41 534 444.5 C534.67 445.31 534.93 446.45 535 447.5 C535.27 451.49 535.42 455.52 535 459.5 C534.75 461.91 534.33 464.47 533 466.5 C518.12 489.15 530.08 467.23 512.5 482 C507.07 486.56 503.94 493.46 498.5 498 C495.74 500.3 492.07 501.65 488.5 502 C481.52 502.68 474.47 500.29 467.5 501 C465.86 501.17 464.22 502.86 464 504.5 C463.33 509.47 464.38 514.53 465 519.5 C465.06 519.97 465.92 520.04 466 520.5 C466.61 524.13 466.32 527.88 467 531.5 C467.48 534.04 471.53 539.52 469 542.5 C467.81 543.91 465.33 542.83 463.5 543 Z "
        "M371 413.5 C369.5 415 368.27 416.83 366.5 418 C360.39 422.03 354.14 425.93 347.5 429 C341.86 431.6 339.22 429.83 334.5 427 C329.74 424.15 324.84 421.45 320.5 418 C318.28 416.23 315.86 414.21 315 411.5 C313.59 407.04 314 402.18 314 397.5 C314 397.03 314.97 396.97 315 396.5 C315.31 392.18 314.71 387.82 315 383.5 C315.1 382.07 317.74 379.46 318.5 379 C323.36 376.08 328.62 373.87 333.5 371 C334.31 370.52 334.66 369.42 335.5 369 C337.39 368.06 339.44 367.46 341.5 367 C342.48 366.78 343.54 366.74 344.5 367 C347.25 367.75 350 368.64 352.5 370 C357.37 372.66 361.99 375.78 366.5 379 C368.5 380.43 370.91 382.73 371 385.5 C371.3 394.83 371 404.17 371 413.5 Z "
        "M302 381.5 C302.33 382.17 302.98 382.76 303 383.5 C303.31 393.5 305.07 403.72 303 413.5 C302.36 416.53 298.21 417.49 295.5 419 C270.55 432.96 276.43 434.71 252.5 418 C244.24 412.23 248.04 412.75 247 405.5 C246.93 405.03 246.03 404.97 246 404.5 C245.69 399.18 245.72 393.83 246 388.5 C246.06 387.45 246.37 386.35 247 385.5 C249.25 382.46 251.73 379.57 254.5 377 C259.86 372.01 270.57 364.71 278.5 368 C286.84 371.47 294.17 377 302 381.5 Z "
        "M439 381.5 C439.33 391.5 441.45 401.6 440 411.5 C439.52 414.77 435.93 416.76 433.5 419 C431.73 420.63 429.57 421.78 427.5 423 C423.9 425.12 420.39 427.49 416.5 429 C414.3 429.85 411.79 430.57 409.5 430 C405.16 428.91 386.45 419.75 385 414.5 C382.15 404.22 382.51 392.87 385 382.5 C385.94 378.58 391.16 377.26 394.5 375 C397.34 373.08 400.36 371.38 403.5 370 C405.72 369.03 408.11 368.43 410.5 368 C411.81 367.76 413.23 367.6 414.5 368 C426.43 371.73 428.4 374.3 439 381.5 Z "
        "M335 473.5 C329.47 479.03 336.28 472.88 327.5 478 C325.02 479.44 323 481.59 320.5 483 C317.64 484.61 314.68 486.2 311.5 487 C309.24 487.57 306.75 487.6 304.5 487 C297.59 485.16 294.33 480.71 288.5 477 C287.61 476.43 286.35 476.62 285.5 476 C283.79 474.75 281.28 473.6 281 471.5 C276.67 439.23 277.4 441.2 305.5 426 C309.22 423.99 314.76 427.36 317.5 429 C322.26 431.85 326.99 434.78 331.5 438 C332.84 438.96 334.84 439.86 335 441.5 C336.05 452.12 335 462.83 335 473.5 Z "
        "M406 472.5 C404.17 474 402.51 475.75 400.5 477 C393.66 481.26 386.77 485.51 379.5 489 C378.3 489.58 376.74 489.5 375.5 489 C371.62 487.45 368.07 485.17 364.5 483 C360.39 480.5 356.24 478.02 352.5 475 C351.02 473.81 349.37 472.36 349 470.5 C348.15 466.25 348.69 461.82 349 457.5 C349.03 457.03 349.97 456.97 350 456.5 C350.31 452.18 349.73 447.82 350 443.5 C350.07 442.45 350.25 441.25 351 440.5 C353.19 438.31 355.83 436.58 358.5 435 C364.02 431.73 369.57 428.43 375.5 426 C379.31 424.44 383.61 427.35 386.5 429 C391.56 431.89 396.67 434.74 401.5 438 C402.87 438.92 404.81 439.86 405 441.5 C406.02 450.11 404.68 458.84 405 467.5 C405.02 467.97 405.91 468.04 406 468.5 C406.26 469.81 406 471.17 406 472.5 Z"
    )

    box_size = 13 * mm
    box_x = MARGIN_X
    # O header background vai de PAGE_H - 18*mm até PAGE_H
    box_y = PAGE_H - 15.5 * mm

    # 1. Desenhar a borda arredondada dourada com fundo escuro
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1)
    canvas.setFillColor(colors.HexColor("#0a0a0f"))
    canvas.roundRect(box_x, box_y, box_size, box_size, 2.5 * mm, stroke=1, fill=1)

    # 2. Desenhar o icone do cerebro centralizado no box
    try:
        w_mm = 8.5 * mm
        h_mm = 8.5 * mm
        x_off = box_x + (box_size - w_mm) / 2.0
        y_off = box_y + (box_size - h_mm) / 2.0

        vb_minx, vb_miny, vb_w, vb_h = 220, 230, 360, 340
        scale_x = w_mm / vb_w
        scale_y = h_mm / vb_h
        
        canvas.saveState()
        canvas.translate(x_off, y_off + h_mm)
        canvas.scale(scale_x, -scale_y)
        canvas.translate(-vb_minx, -vb_miny)
        
        p = canvas.beginPath()
        for cmd, args_str in re.findall(r'([MCZ])([^MCZ]*)', logo_path_d):
            nums = [float(n) for n in re.findall(r"[-+]?[0-9]*\.?[0-9]+", args_str)]
            if cmd == 'M':
                p.moveTo(nums[0], nums[1])
            elif cmd == 'C':
                for i in range(0, len(nums), 6):
                    p.curveTo(nums[i], nums[i+1], nums[i+2], nums[i+3], nums[i+4], nums[i+5])
            elif cmd == 'Z':
                p.close()
                pass
                
        canvas.setFillColor(GOLD)
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(0)
        canvas.drawPath(p, stroke=0, fill=1)
        canvas.restoreState()
    except Exception as e:
        pass

    # 3. Textos "Hive Mind" e "ENTERPRISE AI"
    text_x = box_x + box_size + 4 * mm

    canvas.setFillColor(GOLD)
    canvas.setFont("Helvetica-Bold", 14)
    canvas.drawString(text_x, box_y + 8.5 * mm, "Hive Mind")

    canvas.setFillColor(colors.HexColor("#a1a1aa"))
    canvas.setFont("Helvetica", 6.5)
    canvas.drawString(text_x, box_y + 4.5 * mm, "E N T E R P R I S E   A I")

    # Subtítulo direita
    canvas.setFillColor(MUTED_TXT)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(
        PAGE_W - MARGIN_X, PAGE_H - 12 * mm,
        f"Plano de Execução · {project_name}"
    )

    # ── Rodapé ──────────────────────────────────────────────────────────────
    canvas.setStrokeColor(GOLD_DIM)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_X, 14 * mm, PAGE_W - MARGIN_X, 14 * mm)

    canvas.setFillColor(MUTED_TXT)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(MARGIN_X, 9 * mm, f"Gerado pelo Hive Mind · {user_name} · {datetime.now().strftime('%d/%m/%Y')}")
    canvas.drawRightString(PAGE_W - MARGIN_X, 9 * mm, f"Página {doc.page}")

    canvas.restoreState()


def generate_pdf(
    markdown_content: str,
    project_name: str,
    user_name: str = "Usuário",
    doc_type: str = "execution_plan",
    doc_title: str = "",
) -> bytes:
    """Converte o conteúdo Markdown em um PDF profissional com identidade Hive Mind.

    Args:
        markdown_content: Conteúdo Markdown a converter.
        project_name: Nome do projeto/empresa.
        user_name: Nome do usuário.
        doc_type: Tipo do documento (ex: 'swot', 'canvas', 'pitch_deck', etc.).
        doc_title: Título do documento para a capa. Se vazio, usa o padrão do tipo.
    """
    _titles = {
        "execution_plan":     "Plano de Execução Estratégico",
        "swot":               "Análise SWOT Estratégica",
        "canvas":             "Business Model Canvas",
        "pitch_deck":         "Pitch Deck",
        "proposta_comercial": "Proposta Comercial",
        "modelo_contrato":    "Modelo de Contrato",
        "pesquisa_mercado":   "Pesquisa de Mercado",
        "orientacao_orgao":   "Guia de Processo Público",
    }
    cover_title = doc_title or _titles.get(doc_type, "Documento Estratégico")

    buffer = BytesIO()

    def on_page(canvas, doc):
        _draw_header_footer(canvas, doc, project_name, user_name)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=MARGIN_X,
        leftMargin=MARGIN_X,
        topMargin=MARGIN_T,
        bottomMargin=MARGIN_B,
        title=f"{cover_title} — {project_name}",
        author="Hive Mind",
    )

    # ─── Estilos ──────────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "HiveTitle",
        parent=styles["Title"],
        fontSize=22,
        textColor=GOLD,
        spaceAfter=6,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )

    subtitle_style = ParagraphStyle(
        "HiveSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=BODY_TXT,
        spaceAfter=20,
        alignment=TA_CENTER,
    )

    heading1_style = ParagraphStyle(
        "HiveH1",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=GOLD,
        spaceBefore=18,
        spaceAfter=10,
        fontName="Helvetica-Bold",
        borderPad=4,
    )

    heading2_style = ParagraphStyle(
        "HiveH2",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=GOLD_DIM,
        spaceBefore=14,
        spaceAfter=7,
        fontName="Helvetica-Bold",
    )

    heading3_style = ParagraphStyle(
        "HiveH3",
        parent=styles["Heading3"],
        fontSize=11,
        textColor=BODY_TXT,
        spaceBefore=10,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )

    body_style = ParagraphStyle(
        "HiveBody",
        parent=styles["Normal"],
        fontSize=9.5,
        textColor=BODY_TXT,
        spaceAfter=5,
        leading=14,
    )
    
    table_body_style = ParagraphStyle(
        "HiveTableBody",
        parent=styles["Normal"],
        fontSize=9.5,
        textColor=LIGHT_TXT,
        leading=13,
    )

    bullet_style = ParagraphStyle(
        "HiveBullet",
        parent=styles["Normal"],
        fontSize=9.5,
        textColor=BODY_TXT,
        spaceAfter=4,
        leading=14,
        leftIndent=12,
    )

    checklist_style = ParagraphStyle(
        "HiveChecklist",
        parent=styles["Normal"],
        fontSize=9.5,
        textColor=GREEN,
        spaceAfter=4,
        leading=14,
        leftIndent=12,
    )

    note_style = ParagraphStyle(
        "HiveNote",
        parent=styles["Normal"],
        fontSize=9,
        textColor=BODY_TXT,
        spaceAfter=4,
        leading=13,
        leftIndent=8,
        fontName="Helvetica-Oblique",
    )

    elements = []

    # ─── Capa ─────────────────────────────────────────────────────────────────
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(cover_title.upper(), title_style))
    elements.append(Paragraph("Hive Mind · Consultoria Multi-Agentes", subtitle_style))
    elements.append(Spacer(1, 10))

    # Info box
    info_data = [
        ["Projeto", project_name],
        ["Responsável", user_name],
        ["Data de Geração", datetime.now().strftime("%d/%m/%Y")],
        ["Tipo", cover_title],
    ]
    info_table = Table(info_data, colWidths=[50 * mm, 110 * mm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), DARK_MID),
        ("BACKGROUND", (1, 0), (1, -1), DARK_CARD),
        ("FONTNAME",   (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",  (0, 0), (0, -1), GOLD),
        ("TEXTCOLOR",  (1, 0), (1, -1), LIGHT_TXT),
        ("GRID",       (0, 0), (-1, -1), 0.5, GOLD_DIM),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 12))

    # Linha dourada divisória
    line_table = Table([[""]], colWidths=[CONTENT_WIDTH])
    line_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 2, GOLD),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 16))

    # ─── Converter Markdown → elementos PDF ───────────────────────────────────
    lines = markdown_content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            elements.append(Spacer(1, 3))
            i += 1
            continue

        # Headings
        if stripped.startswith("# ") and not stripped.startswith("## "):
            text = _md_inline(stripped[2:])
            elements.append(Paragraph(text, heading1_style))

        elif stripped.startswith("## "):
            text = _md_inline(stripped[3:])
            elements.append(Paragraph(text, heading2_style))

        elif stripped.startswith("### "):
            text = _md_inline(stripped[4:])
            elements.append(Paragraph(text, heading3_style))

        # Checklist
        elif "[ ]" in stripped or "☐" in stripped:
            text = stripped.replace("- [ ]", "☐").replace("* [ ]", "☐").replace("[x]", "☑").replace("[X]", "☑")
            text = _md_inline(text)
            elements.append(Paragraph(text, checklist_style))

        # Bullet / lista
        elif stripped.startswith("- ") or stripped.startswith("* "):
            text = _md_inline(stripped[2:])
            elements.append(Paragraph(f"• {text}", bullet_style))

        # Lista numerada
        elif len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in (". ", ")"):
            rest = stripped[stripped.index(" ") + 1:]
            text = _md_inline(rest)
            elements.append(Paragraph(f"{stripped[0]}. {text}", bullet_style))

        # Sub-bullet (dois espaços antes de -)
        elif line.startswith("  ") and (stripped.startswith("- ") or stripped.startswith("* ")):
            text = _md_inline(stripped[2:])
            sub_style = ParagraphStyle(
                "HiveSub",
                parent=bullet_style,
                leftIndent=24,
                fontSize=9,
                textColor=BODY_TXT,
            )
            elements.append(Paragraph(f"◦ {text}", sub_style))

        # Tabela Markdown
        elif stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|---"):
            headers = [h.strip() for h in stripped.split("|") if h.strip()]
            table_data = [[Paragraph(h, ParagraphStyle("TH", parent=styles["Normal"], fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")) for h in headers]]
            i += 2  # pula separador

            while i < len(lines) and lines[i].strip().startswith("|"):
                row = lines[i].strip()
                cells = [c.strip() for c in row.split("|") if c.strip()]
                # normaliza colunas
                while len(cells) < len(headers):
                    cells.append("")
                cells = cells[:len(headers)]
                table_data.append([Paragraph(_md_inline(c), table_body_style) for c in cells])
                i += 1

            col_count = len(headers)
            col_w = CONTENT_WIDTH / col_count
            t = Table(table_data, colWidths=[col_w] * col_count, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), DARK_MID),
                ("BACKGROUND",    (0, 1), (-1, -1), DARK_CARD),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1), [DARK_CARD, colors.HexColor("#22263a")]),
                ("GRID",          (0, 0), (-1, -1), 0.4, GOLD_DIM),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 8))
            continue  # já avançamos i dentro do loop da tabela

        # Linha horizontal
        elif stripped.startswith("---") or stripped.startswith("==="):
            elements.append(Spacer(1, 6))
            hr = Table([[""]], colWidths=[CONTENT_WIDTH])
            hr.setStyle(TableStyle([
                ("LINEBELOW", (0, 0), (-1, -1), 0.8, GOLD_DIM),
            ]))
            elements.append(hr)
            elements.append(Spacer(1, 6))

        # Citação / nota
        elif stripped.startswith(">"):
            text = _md_inline(stripped.lstrip("> "))
            elements.append(Paragraph(f"» {text}", note_style))

        # Parágrafo normal
        else:
            text = _md_inline(stripped)
            if text:
                elements.append(Paragraph(text, body_style))

        i += 1

    # ─── Rodapé final ─────────────────────────────────────────────────────────
    elements.append(Spacer(1, 20))
    final_hr = Table([[""]], colWidths=[CONTENT_WIDTH])
    final_hr.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1, GOLD),
    ]))
    elements.append(final_hr)
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(
        "Documento gerado com exclusividade pelo <b>Hive Mind</b> · Plataforma de Mentoria Empresarial Multi-Agentes.",
        ParagraphStyle("FinaleNote", parent=styles["Normal"], fontSize=8, textColor=MUTED_TXT, alignment=TA_CENTER)
    ))

    # Build com canvas hook em todas as páginas
    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)

    pdf_bytes = buffer.getvalue()
    buffer.close()

    logger.info(f"PDF Hive Mind gerado com sucesso ({len(pdf_bytes)} bytes)")
    return pdf_bytes


# ─── Helpers inline Markdown ───────────────────────────────────────────────────

def _md_inline(text: str) -> str:
    """Converte bold/italic/code básico de Markdown para tags ReportLab."""
    import re
    # Bold **texto** ou __texto__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    # Italic *texto* ou _texto_
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'_([^_]+?)_', r'<i>\1</i>', text)
    # Code `texto`
    text = re.sub(r'`(.+?)`', r'<font face="Courier">\1</font>', text)
    # Escapar & que não faça parte de entidade
    text = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#)', '&amp;', text)
    # Remove < e > soltos que não são tags
    text = re.sub(r'<(?!/?(?:b|i|u|font|br))', '&lt;', text)
    return text
