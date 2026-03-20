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

# Prompt para o Gemini gerar o plano de execução
SUMMARIZATION_PROMPT = """Você é um Estrategista-Chefe especializado em Planos de Execução para startups e PMEs brasileiras.
Com base na transcrição da sessão de mentoria, gere um plano de ação ESTRATÉGICO e EXECUTÁVEL.

## FORMATO OBRIGATÓRIO DO PLANO:

### # Resumo Executivo
[Apresentação em 3 parágrafos: o que é, proposta de valor, diferenciação]

### ## Diagnóstico do Projeto
[Pontos fortes identificados + principais desafios + oportunidades]

### ## 1. Roadmap Financeiro
- **Investimento Inicial Estimado:** R$ [valor]
- **Custos Mensais Fixos:** R$ [valor]
- **Ponto de Equilíbrio:** [meses]
- **Margem Bruta Projetada:** [%]
- **Fontes de Financiamento Sugeridas:** [opções]

### ## 2. Estrutura Jurídica Recomendada
- **Tipo Societário:** [LTDA/EIRELI/Startup]
- **CNPJ e Inscrições:** [o que precisa]
- **Contratos Essenciais:** [lista]
- **Conformidade LGPD:** [sim/não + ações]

### ## 3. Estratégia de Marketing e Vendas
- **Posicionamento:** [frase de impacto]
- **ICP (Cliente Ideal):** [perfil detalhado]
- **Canais Prioritários:** [top 3 com justificativa]
- **CAC Alvo:** R$ [valor]
- **LTV Mínimo:** R$ [valor]
- **Go-to-Market:** [fases]

### ## 4. Arquitetura Técnica
- **Stack Recomendada:** [tecnologias com razão]
- **Infraestrutura:** [nuvem + specs]
- **MVP - Funcionalidades Essenciais:** [top 5]
- **Escalabilidade:** [previsão de crescimento]

### ## 5. Cronograma de Execução (12 semanas)
- **Semanas 1-2:** [ações]
- **Semanas 3-4:** [ações]
- **Semanas 5-8:** [ações]
- **Semanas 9-12:** [ações]

### ## 6. KPIs e Métricas de Sucesso
| Métrica | Meta | Frequência |
|---------|------|------------|
| [KPI 1] | [valor] | [semanal/mensal] |
| [KPI 2] | [valor] | [semanal/mensal] |
| [KPI 3] | [valor] | [semanal/mensal] |

### ## 7. Riscos e Planos de Mitigação
| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| [risco] | [alta/média/baixa] | [alto/médio/baixo] | [ação] |

### ## 8. Checklist de Ações Imediatas (Esta Semana)
- [ ] [Ação 1 - responsável e prazo]
- [ ] [Ação 2 - responsável e prazo]
- [ ] [Ação 3 - responsável e prazo]
- [ ] [Ação 4 - responsável e prazo]
- [ ] [Ação 5 - responsável e prazo]

### ## 9. Recursos Necessários
- **Pessoas:** [equipe necessária]
- **Ferramentas:** [softwares/apps]
- **Orçamento Adicional:** R$ [valor]

### ## 10. Próximos Passos
1. [Ação prioritária]
2. [Ação prioritária]
3. [Ação prioritária]

---
Use números concretos e valores realistas para o mercado brasileiro.
Inclua datas de deadline quando possível.
Considere a realidade fiscal e trabalhista do Brasil.

TRANSCRIÇÃO DA SESSÃO:
{transcript}
"""


async def generate_execution_plan(
    transcript: str,
    project_name: str,
    user_name: str = "Usuário",
    additional_context: str = ""
) -> dict:
    """
    Gera o plano de execução usando Gemini 2.5 Flash.
    
    Args:
        transcript: Transcrição completa da sessão
        project_name: Nome do projeto
        user_name: Nome do usuário
        additional_context: Contexto adicional para personalização
    
    Returns:
        dict com 'markdown' (conteúdo) e 'pdf_bytes' (arquivo PDF)
    """
    
    # Gerar conteúdo com Gemini 2.5 Flash
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    # Incluir contexto adicional se disponível
    full_context = transcript
    if additional_context:
        full_context = f"{transcript}\n\nCONTEXTO ADICIONAL:\n{additional_context}"
    
    response = await asyncio.to_thread(
        model.generate_content,
        SUMMARIZATION_PROMPT.format(transcript=full_context),
        generation_config=genai.GenerationConfig(
            temperature=0.4,
            max_output_tokens=8192,
        ),
    )
    
    markdown_content = response.text
    logger.info(f"Plano de execução gerado ({len(markdown_content)} chars)")
    
    # Gerar PDF
    pdf_bytes = generate_pdf(markdown_content, project_name, user_name)
    
    return {
        "markdown": markdown_content,
        "pdf_bytes": pdf_bytes,
        "project_name": project_name,
        "user_name": user_name,
        "generated_at": datetime.now().isoformat(),
    }


def generate_pdf(markdown_content: str, project_name: str, user_name: str = "Usuário") -> bytes:
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
        fontSize=18,
        textColor=colors.HexColor("#1f2937"),
        spaceBefore=20,
        spaceAfter=12,
    )
    
    subheading_style = ParagraphStyle(
        "CustomSubheading",
        parent=styles["Heading2"],
        fontSize=14,
        textColor=colors.HexColor("#4f46e5"),
        spaceBefore=15,
        spaceAfter=8,
    )
    
    subsection_style = ParagraphStyle(
        "CustomSubsection",
        parent=styles["Heading3"],
        fontSize=11,
        textColor=colors.HexColor("#6366f1"),
        spaceBefore=10,
        spaceAfter=5,
    )
    
    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#374151"),
        spaceAfter=6,
        leading=14,
    )
    
    checklist_style = ParagraphStyle(
        "Checklist",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#059669"),
        spaceAfter=4,
        leading=14,
        leftIndent=10,
    )
    
    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.white,
    )
    
    elements = []
    
    # Capa
    elements.append(Spacer(1, 40))
    elements.append(Paragraph("MENTORIA AI", title_style))
    elements.append(Paragraph("Plano de Execução Estratégico", subtitle_style))
    elements.append(Spacer(1, 15))
    
    # Info box
    info_data = [
        ["Projeto", project_name],
        ["Cliente", user_name],
        ["Data", datetime.now().strftime("%d/%m/%Y")],
        ["Versão", "1.0"],
    ]
    info_table = Table(info_data, colWidths=[80, 90])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#374151")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 20))
    
    # Linha divisória
    line_table = Table([[""]], colWidths=[170 * mm])
    line_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 2, colors.HexColor("#6366f1")),
    ]))
    elements.append(line_table)
    elements.append(Spacer(1, 25))
    
    # Converter Markdown para elementos PDF
    lines = markdown_content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if not line:
            elements.append(Spacer(1, 4))
            i += 1
            continue
        
        # Heading 1: # Título
        if line.startswith("# ") and not line.startswith("## "):
            text = line[2:].replace("**", "")
            elements.append(Paragraph(text, heading_style))
        
        # Heading 2: ## Título
        elif line.startswith("## "):
            text = line[3:].replace("**", "")
            elements.append(Paragraph(text, subheading_style))
        
        # Heading 3: ### Título
        elif line.startswith("### "):
            text = line[4:].replace("**", "")
            elements.append(Paragraph(text, subsection_style))
        
        # Checklist item: - [ ]
        elif "[ ]" in line or "☐" in line:
            text = line.replace("- [ ]", "☐").replace("* [ ]", "☐")
            text = text.replace("**", "<b>", 1).replace("**", "</b>", 1) if "**" in line else text
            elements.append(Paragraph(text, checklist_style))
        
        # Bullet point
        elif line.startswith("- ") or line.startswith("* "):
            text = line[2:].replace("**", "<b>", 1).replace("**", "</b>", 1)
            elements.append(Paragraph(f"• {text}", body_style))
        
        # Numbered list
        elif line[0].isdigit() and ". " in line[:5]:
            text = line[line.index(". ")+2:]
            text = text.replace("**", "<b>", 1).replace("**", "</b>", 1)
            elements.append(Paragraph(text, body_style))
        
        # Table header (pipe-separated)
        elif line.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|---"):
            # Extract headers
            headers = [h.strip() for h in line.split("|") if h.strip()]
            table_data = [headers]
            
            # Skip separator line
            i += 1
            
            # Extract data rows
            while i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
                i += 1
                row = lines[i].strip()
                cells = [c.strip() for c in row.split("|") if c.strip()]
                if cells:
                    table_data.append(cells)
            
            # Ensure all rows have same column count
            col_count = len(headers)
            for j, row in enumerate(table_data[1:]):
                while len(row) < col_count:
                    row.append("")
                table_data[j + 1] = row[:col_count]
            
            if table_data:
                t = Table(table_data, colWidths=[170 * mm / col_count] * col_count)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6366f1")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]))
                elements.append(t)
                elements.append(Spacer(1, 10))
        
        # Horizontal rule
        elif line.startswith("---"):
            elements.append(Spacer(1, 10))
            hr_table = Table([[""]], colWidths=[170 * mm])
            hr_table.setStyle(TableStyle([
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ]))
            elements.append(hr_table)
            elements.append(Spacer(1, 10))
        
        # Regular paragraph
        else:
            text = line.replace("**", "<b>", 1).replace("**", "</b>", 1)
            elements.append(Paragraph(text, body_style))
        
        i += 1
    
    # Rodapé
    elements.append(Spacer(1, 30))
    footer_line = Table([[""]], colWidths=[170 * mm])
    footer_line.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#e5e7eb")),
    ]))
    elements.append(footer_line)
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
            f"Gerado automaticamente pelo Mentoria AI • {datetime.now().strftime('%d/%m/%Y')}",
            footer_style,
        )
    )
    
    doc.build(elements)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    logger.info(f"PDF gerado com sucesso ({len(pdf_bytes)} bytes)")
    return pdf_bytes
