"""
Mentoria AI - Gerador de Plano de Execução (PDF)
==================================================
Recebe a transcrição da sessão, envia ao Gemini 1.5 Pro para sumarização
e gera um PDF profissional com o plano de ação.
"""

import asyncio
import logging
from datetime import datetime
from io import BytesIO

import google.generativeai as genai
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
from reportlab.lib.enums import TA_CENTER, TA_LEFT

logger = logging.getLogger("mentoria-ai.pdf")

# Prompt para o Gemini 1.5 Pro gerar o plano de execução
SUMMARIZATION_PROMPT = """Você é um especialista em gerar Planos de Execução para projetos. 
Com base na transcrição da sessão de mentoria abaixo, gere um plano de ação detalhado.

FORMATO DO PLANO:
1. **Resumo Executivo** (2-3 parágrafos resumindo o projeto e as recomendações principais)
2. **Análise Financeira** (custos estimados, modelo de receita, ponto de equilíbrio)
3. **Aspectos Jurídicos** (tipo societário recomendado, contratos necessários, conformidade)
4. **Estratégia de Marketing** (canais, posicionamento, go-to-market)
5. **Arquitetura Técnica** (stack recomendada, infraestrutura, escalabilidade)
6. **Cronograma de Execução** (fases com prazos estimados em semanas)
7. **Riscos e Mitigações** (principais riscos identificados e como mitigar)
8. **Próximos Passos Imediatos** (3-5 ações para começar esta semana)

Use Markdown para formatação. Seja específico, use números concretos quando possível.
Considere o contexto brasileiro.

TRANSCRIÇÃO DA SESSÃO:
{transcript}
"""


async def generate_execution_plan(transcript: str, project_name: str) -> dict:
    """
    Gera o plano de execução usando Gemini 1.5 Pro.
    
    Returns:
        dict com 'markdown' (conteúdo) e 'pdf_bytes' (arquivo PDF)
    """
    
    # Gerar conteúdo com Gemini 2.5 Flash
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    response = await asyncio.to_thread(
        model.generate_content,
        SUMMARIZATION_PROMPT.format(transcript=transcript),
        generation_config=genai.GenerationConfig(
            temperature=0.3,
            max_output_tokens=4096,
        ),
    )
    
    markdown_content = response.text
    logger.info(f"Plano de execução gerado ({len(markdown_content)} chars)")
    
    # Gerar PDF
    pdf_bytes = generate_pdf(markdown_content, project_name)
    
    return {
        "markdown": markdown_content,
        "pdf_bytes": pdf_bytes,
    }


def generate_pdf(markdown_content: str, project_name: str) -> bytes:
    """Converte o conteúdo Markdown em um PDF profissional."""
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
    )
    
    # Estilos
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Title"],
        fontSize=24,
        textColor=colors.HexColor("#6366f1"),
        spaceAfter=10,
        alignment=TA_CENTER,
    )
    
    subtitle_style = ParagraphStyle(
        "CustomSubtitle",
        parent=styles["Normal"],
        fontSize=12,
        textColor=colors.HexColor("#6b7280"),
        spaceAfter=30,
        alignment=TA_CENTER,
    )
    
    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#4f46e5"),
        spaceBefore=20,
        spaceAfter=10,
    )
    
    subheading_style = ParagraphStyle(
        "CustomSubheading",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=colors.HexColor("#6366f1"),
        spaceBefore=15,
        spaceAfter=8,
    )
    
    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#374151"),
        spaceAfter=8,
        leading=14,
    )
    
    elements = []
    
    # Capa
    elements.append(Spacer(1, 60))
    elements.append(Paragraph("🧠 MENTORIA AI", title_style))
    elements.append(Paragraph("Plano de Execução", subtitle_style))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"<b>Projeto:</b> {project_name}", body_style))
    elements.append(
        Paragraph(
            f"<b>Data:</b> {datetime.now().strftime('%d/%m/%Y às %H:%M')}",
            body_style,
        )
    )
    elements.append(Spacer(1, 10))
    
    # Linha divisória
    line_data = [["" * 80]]
    line_table = Table(line_data, colWidths=[170 * mm])
    line_table.setStyle(
        TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#e5e7eb")),
        ])
    )
    elements.append(line_table)
    elements.append(Spacer(1, 20))
    
    # Converter Markdown para elementos PDF
    lines = markdown_content.split("\n")
    
    for line in lines:
        line = line.strip()
        
        if not line:
            elements.append(Spacer(1, 5))
            continue
        
        # Headings
        if line.startswith("## "):
            text = line[3:].replace("**", "")
            elements.append(Paragraph(text, subheading_style))
        elif line.startswith("# "):
            text = line[2:].replace("**", "")
            elements.append(Paragraph(text, heading_style))
        elif line.startswith("- ") or line.startswith("* "):
            text = line[2:]
            text = text.replace("**", "<b>", 1).replace("**", "</b>", 1)
            elements.append(Paragraph(f"• {text}", body_style))
        elif line.startswith("1.") or line.startswith("2.") or line.startswith("3."):
            text = line
            text = text.replace("**", "<b>", 1).replace("**", "</b>", 1)
            elements.append(Paragraph(text, body_style))
        else:
            text = line.replace("**", "<b>", 1).replace("**", "</b>", 1)
            elements.append(Paragraph(text, body_style))
    
    # Rodapé
    elements.append(Spacer(1, 30))
    elements.append(line_table)
    elements.append(Spacer(1, 10))
    
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#9ca3af"),
        alignment=TA_CENTER,
    )
    elements.append(
        Paragraph(
            "Gerado automaticamente pelo Mentoria AI • mentoria-ai.com",
            footer_style,
        )
    )
    
    doc.build(elements)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    logger.info(f"PDF gerado com sucesso ({len(pdf_bytes)} bytes)")
    return pdf_bytes
