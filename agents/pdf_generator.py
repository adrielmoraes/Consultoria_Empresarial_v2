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
MUTED_TXT= colors.HexColor("#94a3b8")
GREEN    = colors.HexColor("#10b981")
WHITE    = colors.white

PAGE_W, PAGE_H = A4
MARGIN_X = 20 * mm
MARGIN_T = 30 * mm  # espaço para o cabeçalho
MARGIN_B = 22 * mm  # espaço para o rodapé

CONTENT_WIDTH = PAGE_W - 2 * MARGIN_X

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


# ─── Canvas hooks: cabeçalho e rodapé em todas as páginas ─────────────────────

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

    # Logo text "HIVE MIND"
    canvas.setFillColor(GOLD)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(MARGIN_X, PAGE_H - 12 * mm, "HIVE MIND")

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


def generate_pdf(markdown_content: str, project_name: str, user_name: str = "Usuário") -> bytes:
    """Converte o conteúdo Markdown em um PDF profissional com identidade Hive Mind."""

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
        title=f"Plano de Execução — {project_name}",
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
        textColor=MUTED_TXT,
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
        textColor=LIGHT_TXT,
        spaceBefore=10,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )

    body_style = ParagraphStyle(
        "HiveBody",
        parent=styles["Normal"],
        fontSize=9.5,
        textColor=LIGHT_TXT,
        spaceAfter=5,
        leading=14,
    )

    bullet_style = ParagraphStyle(
        "HiveBullet",
        parent=styles["Normal"],
        fontSize=9.5,
        textColor=LIGHT_TXT,
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
        textColor=MUTED_TXT,
        spaceAfter=4,
        leading=13,
        leftIndent=8,
        fontName="Helvetica-Oblique",
    )

    elements = []

    # ─── Capa ─────────────────────────────────────────────────────────────────
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("PLANO DE EXECUÇÃO ESTRATÉGICO", title_style))
    elements.append(Paragraph("Hive Mind · Consultoria Multi-Agentes", subtitle_style))
    elements.append(Spacer(1, 10))

    # Info box
    info_data = [
        ["Projeto", project_name],
        ["Consultor(a)", user_name],
        ["Data de Geração", datetime.now().strftime("%d/%m/%Y")],
        ["Versão", "2.0"],
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
                textColor=MUTED_TXT,
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
                table_data.append([Paragraph(_md_inline(c), body_style) for c in cells])
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
