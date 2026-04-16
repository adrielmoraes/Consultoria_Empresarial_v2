import os
import sys

# Garante que as importações da pasta atual funcionem
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_generator import generate_pdf

def test_generate_pdfs():
    output_dir = os.path.join(os.path.dirname(__file__), "test_pdfs")
    os.makedirs(output_dir, exist_ok=True)

    project_name = "TechInova Start"
    user_name = "Adriel Moraes"

    # 1. Análise SWOT (Com Tabelas)
    markdown_swot = """# Análise SWOT Estratégica: TechInova Start

Aqui está uma avaliação estratégica cruzada do seu negócio com o mercado.

## SWOT Matrix
| Forças (Strengths) | Fraquezas (Weaknesses) |
|---|---|
| - Equipe fundadora experiente em tecnologia | - Fluxo de caixa inicial limitado |
| - Arquitetura escalável baseada em microsserviços | - Baixo reconhecimento da marca no mercado |
| - Algoritmo proprietário com IA generativa | - Dependência de fornecedores de nuvem terceiros |

| Oportunidades (Opportunities) | Ameaças (Threats) |
|---|---|
| - Demanda crescente no setor de healthtech | - Novos competidores globais com grandes investimentos |
| - Expansão de conectividade 5G no Brasil | - Mudanças regulatórias (nova LGPD) |
| - Possibilidade de parcerias com cooperativas | - Inflação de custos para importação de insumos |

## Ações Cruzadas Recomendadas
*   **Acelerar Aquisição (Força + Oportunidade):** Usar a escalabilidade técnica para capturar os clientes oriundos da nova adoção em massa no setor hospitalar.
*   **Fortalecer Caixa (Oportunidade + Fraqueza):** Lançar um Early Adopter pass focado puramente nas assinaturas premium anuais para reaquecer capital.
"""

    b_swot = generate_pdf(
        markdown_content=markdown_swot,
        project_name=project_name,
        user_name=user_name,
        doc_type="swot",
        doc_title="Análise SWOT Estratégica"
    )
    with open(os.path.join(output_dir, "01_teste_swot.pdf"), "wb") as f:
        f.write(b_swot)


    # 2. Checklist Processos Público (Formatos de listas customizados)
    markdown_guia = """# Guia Rápido: Registro de Marca no INPI

Este é um guia não oficial para orientação do empreendedor visando proteger sua marca no Brasil.

## Passo a Passo para o INPI

1. **Pesquisa Prévia (Busca de Anterioridade)**
   É necessário averiguar se já existe alguma marca com nome similar registrada na sua mesma classe de NCL.

2. **Categorização de Classe NCL**
   - Softwares: Classe 09.
   - Serviços de educação: Classe 41.
   - Serviços online e SaaS: Classe 42.

3. **Pagamento da GRU e Protocolo**
   O custo inicial gira em torno de R$ 142,00 para empreendedores (MEI ou EPP).

### Checklist de Documentos

- [ ] Contrato social (ou CCMEI para MEI).
- [ ] Logotipo em alta resolução (se aplicável, formato JPG).
- [ ] Procuração simples (se feito por terceiros).

> **Lembrete Legal:** Considere trabalhar junto a um advogado ou escritório especializado para evitar indeferimentos na última fase.
"""

    b_guia = generate_pdf(
        markdown_content=markdown_guia,
        project_name=project_name,
        user_name=user_name,
        doc_type="orientacao_orgao",
        doc_title="Guia de Processo Público"
    )
    with open(os.path.join(output_dir, "02_teste_guia_publico.pdf"), "wb") as f:
        f.write(b_guia)


    # 3. Modelo de Contrato (Aparência formal/blocos de texto grandes)
    markdown_contrato = """# Contrato Simbólico de Prestação de Serviços (Modelo base)

Pelo presente instrumento, acordam de comum acordo, sob as diretrizes do código civil brasileiro:

## Cláusula 1ª - Do Objeto
A CONTRATADA se compromete a entregar uma infraestrutura baseada no plano comercializado, englobando a configuração de painéis e servidores cloud privados.

## Cláusula 2ª - Do Prazo e Validade
1. O período do contrato vigora por 12 (doze) meses contínuos.
2. Não há multa para encerramento desde que notificado com 30 (trinta) dias de antecedência.

## Cláusula 3ª - Das Obrigações
*   Manter sigilo de dados em conformidade com a LGPD.
*   Prover updates e manutenções de segurança pelo menos 2 vezes ao trimestre.

**Assinaturas (Aviso: Uso não-oficial. Documento meramente exemplar).**
"""

    b_contrato = generate_pdf(
        markdown_content=markdown_contrato,
        project_name=project_name,
        user_name=user_name,
        doc_type="modelo_contrato",
        doc_title="Modelo de Contrato NDA"
    )
    with open(os.path.join(output_dir, "03_teste_modelo_contrato.pdf"), "wb") as f:
        f.write(b_contrato)

    print(f"✅ PDFs de teste gerados com sucesso na pasta: {output_dir}")
    print("Arquivos gerados:")
    print(" - 01_teste_swot.pdf")
    print(" - 02_teste_guia_publico.pdf")
    print(" - 03_teste_modelo_contrato.pdf")


if __name__ == "__main__":
    test_generate_pdfs()
