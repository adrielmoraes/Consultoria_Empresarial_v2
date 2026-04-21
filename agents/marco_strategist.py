"""
Mentoria AI — Marco Strategist (Gerador de Documentos Desacoplado)
===================================================================
Centraliza toda a lógica de geração de documentos do Marco (Estrategista).
Usa ProcessPoolExecutor para isolar o trabalho pesado (LLM + PDF) do
event loop principal do LiveKit, evitando travamentos no áudio.

ARQUITETURA:
    ┌─────────────────────────┐
    │  worker.py (Event Loop) │  ← Áudio em tempo real, LiveKit WebRTC
    │  HostAgent → tools      │
    │    ↓ (non-blocking)     │
    │  MarcoStrategist        │  ← Fachada async que delega ao pool
    │    ↓                    │
    │  ProcessPoolExecutor    │  ← Processo separado, livre do GIL
    │    ↓                    │
    │  _worker_generate_doc() │  ← Chama Gemini API + pdf_generator
    └─────────────────────────┘

O ProcessPoolExecutor roda em outro processo do SO, eliminando
a contenção do GIL que travava o áudio quando o Marco gerava PDFs.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Optional

logger = logging.getLogger("mentoria-ai")

# ── Pool global de processos para o Marco ──────────────────────────────────────
# max_workers=1 porque raramente há mais de 1 documento sendo gerado ao mesmo
# tempo na mesma sessão. Economiza RAM (~50MB por worker extra).
_marco_pool: Optional[ProcessPoolExecutor] = None


def _get_pool() -> ProcessPoolExecutor:
    """Lazy-init do ProcessPoolExecutor (evita fork no import)."""
    global _marco_pool
    if _marco_pool is None:
        _marco_pool = ProcessPoolExecutor(max_workers=1)
    return _marco_pool


# ═══════════════════════════════════════════════════════════════════════════════
# FUNÇÕES QUE RODAM NO PROCESSO FILHO (pickle-safe, sem referências ao LiveKit)
# ═══════════════════════════════════════════════════════════════════════════════

def _worker_call_llm(
    api_key: str,
    prompt: str,
    temperature: float = 0.65,
    max_output_tokens: int = 66000,
) -> str:
    """Chama o Gemini API dentro do processo filho. Retorna markdown."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ),
    )
    text = resp.text.strip()
    # Remove wrapper de código se o LLM adicionar
    for prefix in ("```markdown", "```"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _worker_generate_search_query(api_key: str, prompt: str) -> str:
    """Gera uma query curta para pesquisa web no processo filho."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=60),
    )
    query = resp.text.strip().replace('"', "").replace("'", "").strip()[:100]
    return query


def _worker_web_search(query: str) -> str:
    """Executa pesquisa no DuckDuckGo no processo filho."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore
        results = list(DDGS().text(query, max_results=4, region="br-pt"))
        if results:
            parts = [f"Título: {r.get('title')}\nTrecho: {r.get('body')}" for r in results]
            return "\n\n--- DADOS PESQUISADOS NA WEB ---\n" + "\n\n".join(parts)
    except Exception:
        pass
    return ""


def _worker_generate_pdf(
    markdown_content: str,
    project_name: str,
    user_name: str,
    doc_type: str = "execution_plan",
    doc_title: str = "Plano de Execução",
) -> Optional[bytes]:
    """Gera PDF via reportlab no processo filho. Retorna bytes ou None."""
    try:
        # Importa dentro do processo filho (precisa do sys.path correto)
        import sys
        agents_dir = os.path.dirname(os.path.abspath(__file__))
        if agents_dir not in sys.path:
            sys.path.insert(0, agents_dir)

        from pdf_generator import generate_pdf
        return generate_pdf(
            markdown_content,
            project_name,
            user_name,
            doc_type=doc_type,
            doc_title=doc_title,
        )
    except Exception as e:
        # Log no processo filho (pode não aparecer, mas é seguro)
        print(f"[Marco/Worker] Falha ao gerar PDF: {e}")
        return None


def _worker_full_document_pipeline(
    api_key: str,
    prompt: str,
    review_prompt: Optional[str],
    search_queries: list[str],
    project_name: str,
    user_name: str,
    doc_type: str,
    doc_title: str,
    temperature: float = 0.65,
) -> dict:
    """
    Pipeline completo de geração de documento no processo filho.
    Executa: pesquisa web → draft LLM → revisão LLM → PDF.
    Retorna dict com {markdown, pdf_base64, error}.
    """
    result = {"markdown": "", "pdf_base64": None, "error": None}

    try:
        # 1. Pesquisas web
        web_context = ""
        for query in search_queries:
            if query:
                web_context += _worker_web_search(query)

        # 2. Injeta web_context no prompt
        final_prompt = prompt
        if web_context and "{web_context}" in final_prompt:
            final_prompt = final_prompt.replace("{web_context}", web_context)
        elif web_context:
            final_prompt += f"\n\n{web_context}"

        # 3. Draft com LLM
        draft = _worker_call_llm(api_key, final_prompt, temperature=temperature)

        # 4. Revisão (se fornecida)
        final_text = draft
        if review_prompt and draft:
            full_review = review_prompt.replace("{draft_text}", draft)
            reviewed = _worker_call_llm(api_key, full_review, temperature=0.5)
            if len(reviewed) >= len(draft) * 0.8:
                final_text = reviewed

        result["markdown"] = final_text

        # 5. O PDF agora será gerado no Backend ou via Frontend renderizando markdown,
        # portanto removemos a carga massiva de Base64 daqui para não violar o 
        # MTU limit do LiveKit DataChannel (1008 policy violation).
        result["pdf_base64"] = None

    except Exception as e:
        result["error"] = str(e)
        if not result["markdown"]:
            result["markdown"] = (
                f"# {doc_title}\n\n"
                f"Erro ao gerar documento. Por favor, tente novamente.\n\n"
                f"Contexto: {project_name} — {user_name}"
            )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSE FACHADA ASYNC (roda no event loop principal, delega ao pool)
# ═══════════════════════════════════════════════════════════════════════════════

class MarcoStrategist:
    """
    Fachada assíncrona para toda a geração de documentos do Marco.
    Delega o trabalho pesado ao ProcessPoolExecutor para não travar
    o event loop do LiveKit (áudio, websockets, data packets).

    Uso:
        marco = MarcoStrategist(blackboard, publish_fn)
        await marco.gerar_plano_execucao(user_name, project_name)
    """

    def __init__(
        self,
        blackboard,  # Blackboard (não tipamos para evitar import circular)
        publish_packet_fn,  # async callable(dict) -> None
    ):
        self._blackboard = blackboard
        self._publish_packet = publish_packet_fn
        self._api_key = os.getenv("GEMINI_API_KEY", "").strip()

    async def _emit_progress(self, status: str, progress: int) -> None:
        """Publica data packet de progresso para feedback visual no frontend."""
        try:
            await self._publish_packet({
                "type": "marco_working",
                "status": status,
                "progress": max(0, min(100, progress)),
            })
        except Exception as e:
            logger.debug(f"[Marco] Erro ao emitir progresso: {e}")

    async def _run_in_pool(self, fn, *args):
        """Executa uma função no ProcessPoolExecutor sem bloquear o event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_get_pool(), fn, *args)

    # ──────────────────────────────────────────────────────────────────────
    # Plano de Execução (documento principal)
    # ──────────────────────────────────────────────────────────────────────

    async def gerar_plano_execucao(self, user_name: str, project_name: str) -> None:
        """Gera o Plano de Execução completo e publica no room."""
        self._blackboard.marco_triggered = True
        logger.info("[Marco] Acionando pipeline de Plano de Execução no ProcessPool...")
        self._blackboard.add_message("Sistema", f"Marco iniciou a pesquisa e o processamento do Plano para {user_name}...")

        await self._emit_progress("Marco iniciou as pesquisas de mercado...", 5)

        # Monta os prompts (no processo principal, pois precisa do blackboard)
        from pdf_generator import SUMMARIZATION_PROMPT

        full_transcript = self._blackboard.get_full_transcript()
        transcript_enriched = (
            f"Usuário: {user_name}\n"
            f"Projeto: {project_name}\n"
            f"{{web_context}}\n\n"
            f"{full_transcript}"
        )
        draft_prompt = SUMMARIZATION_PROMPT.format(transcript=transcript_enriched)

        # Query de pesquisa
        search_query_prompt = (
            f"Com base no projeto '{project_name}' e nesta transcrição recente:\n"
            f"{full_transcript[-1500:]}\n"
            f"Gere APENAS UMA QUERY muito curta (ex: 'mercado de tech no brasil tendências') "
            f"para pesquisarmos no Google. NADA DE TEXTO ADICIONAL."
        )

        # Prompt de revisão
        VALIDATION_SECTIONS = [
            "Objetivos SMART (Específicos, Mensuráveis, Atingíveis, Relevantes, com Prazo)",
            "Roadmap Financeiro com valores concretos em R$",
            "Estrutura Jurídica Recomendada",
            "Estratégia de Marketing e Vendas com canais e métricas",
            "Arquitetura Técnica com stack e estimativa de tempo",
            "Cronograma de Execução com divisão de responsabilidades",
            "KPIs e Métricas de Sucesso com metas numéricas",
            "Riscos E seus Planos de Contingência (não apenas mitigação)",
            "Checklist de Ações Imediatas com responsável e prazo por ação",
        ]
        sections_list = "\n".join(f"  {idx+1}. {s}" for idx, s in enumerate(VALIDATION_SECTIONS))
        review_prompt = (
            f"Você é Marco, Estrategista-Chefe do Hive Mind, revisando seu próprio trabalho.\n\n"
            f"Abaixo está o PLANO que você gerou na etapa anterior.\n\n"
            f"## CHECKLIST DE COMPLETUDE OBRIGATÓRIO\n"
            f"Verifique ITEM A ITEM se as seguintes seções estão presentes, detalhadas e com dados concretos:\n"
            f"{sections_list}\n\n"
            f"## SUA TAREFA:\n"
            f"1. Para cada seção faltante ou superficial, DETALHE-A com dados precisos.\n"
            f"2. Garanta que valores financeiros têm números reais (não 'a definir').\n"
            f"3. Garanta que o cronograma tem responsáveis nomeados para cada ação.\n"
            f"4. Garanta que cada risco tem UM plano de mitigação E UM plano de contingência.\n\n"
            f"## INSTRUÇÃO FINAL:\n"
            f"Retorne O PLANO COMPLETO E CORRIGIDO em formato MARKDOWN.\n"
            f"Não adicione introdução, apenas o documento Markdown revisado.\n\n"
            f"--- PLANO ORIGINAL ---\n"
            f"{{draft_text}}\n"
            f"--- FIM DO PLANO ORIGINAL ---"
        )

        await self._emit_progress("Marco pesquisando dados na web...", 15)

        # Gera query de pesquisa no pool
        try:
            search_q = await self._run_in_pool(
                _worker_generate_search_query,
                self._api_key,
                search_query_prompt,
            )
            if len(search_q) < 10:
                search_q = f"{project_name} mercado tendências Brasil 2024"
            logger.info(f"[Marco] Query de pesquisa: {search_q}")
        except Exception as e:
            logger.warning(f"[Marco] Erro ao gerar query: {e}")
            search_q = f"{project_name} mercado tendências Brasil 2024"

        await self._emit_progress("Marco redigindo o Plano com IA...", 30)

        # Pipeline completo no pool (pesquisa + draft + revisão + PDF)
        try:
            result = await self._run_in_pool(
                _worker_full_document_pipeline,
                self._api_key,
                draft_prompt,
                review_prompt,
                [search_q],
                project_name,
                user_name,
                "execution_plan",
                "Plano de Execução",
            )
        except Exception as e:
            logger.error(f"[Marco] Erro no pipeline: {e}")
            result = {
                "markdown": self._generate_fallback_plan(user_name, project_name),
                "pdf_base64": None,
                "error": str(e),
            }

        if result.get("error"):
            logger.warning(f"[Marco] Pipeline com erro (usando resultado parcial): {result['error']}")

        await self._emit_progress("Convertendo para PDF...", 88)

        # Publica resultado apenas em MARKDOWN leve (DataChannel seguro)
        markdown_plan = result.get("markdown", "")
        try:
            packet: dict = {
                "type": "execution_plan",
                "plan": markdown_plan,
                "text": markdown_plan,
            }
            await self._publish_packet(packet)
            await self._emit_progress("Plano de Execução pronto! ✅", 100)
            logger.info("[Marco] Plano de Execução publicado (Marketing only).")
        except Exception as e:
            logger.warning(f"[Marco] Erro ao publicar plano: {e}")

    # ──────────────────────────────────────────────────────────────────────
    # Documento personalizado genérico (SWOT, Canvas, Proposta, etc.)
    # ──────────────────────────────────────────────────────────────────────

    async def gerar_documento_personalizado(
        self,
        doc_type: str,
        doc_title: str,
        user_name: str,
        project_name: str,
        extra_context: str = "",
        extra_vars: Optional[dict] = None,
    ) -> None:
        """Gera qualquer documento do Marco e publica no room."""
        logger.info(f"[Marco] Gerando {doc_title} no ProcessPool...")
        self._blackboard.add_message("Sistema", f"Marco preparando {doc_title}...")

        await self._emit_progress(f"Marco pesquisando sobre {doc_title}...", 10)

        from pdf_generator import DOCUMENT_PROMPTS

        full_transcript = self._blackboard.get_full_transcript()

        # Monta prompt
        prompt_template, _ = DOCUMENT_PROMPTS.get(doc_type, (None, None))
        if prompt_template is None:
            logger.warning(f"[Marco] Tipo desconhecido: {doc_type}. Usando execution_plan.")
            prompt_template, _ = DOCUMENT_PROMPTS["execution_plan"]

        transcript_enriched = (
            f"Usuário: {user_name}\n"
            f"Projeto: {project_name}\n"
            f"Informação adicional: {extra_context}\n"
            f"{{web_context}}\n\n"
            f"{full_transcript}"
        )

        fmt_vars = {
            "transcript": transcript_enriched,
            "projeto": project_name,
            "user_name": user_name,
            "setor": extra_context[:80] if extra_context else project_name,
            "publico": (extra_vars or {}).get("publico", "investidores"),
            "tipo_contrato": (extra_vars or {}).get("tipo_contrato", "prestação de serviços"),
            "tipo_contrato_upper": (extra_vars or {}).get("tipo_contrato_upper", "PRESTAÇÃO DE SERVIÇOS"),
            "partes": (extra_vars or {}).get("partes", "as partes envolvidas"),
            "orgao_processo": extra_context[:120] if extra_context else "processos empresariais",
        }
        try:
            prompt = prompt_template.format(**fmt_vars)
        except KeyError as ke:
            logger.warning(f"[Marco] Chave ausente no template {doc_type}: {ke}")
            prompt = prompt_template.replace("{transcript}", transcript_enriched)

        # Query de pesquisa
        search_query_prompt = (
            f"Projeto '{project_name}', documento '{doc_title}'. "
            f"Contexto adicional: {extra_context[:300]}. "
            f"Gere APENAS UMA QUERY curta para busca no Google sobre este mercado/tema. SEM TEXTO ADICIONAL."
        )

        try:
            search_q = await self._run_in_pool(
                _worker_generate_search_query,
                self._api_key,
                search_query_prompt,
            )
            if len(search_q) < 10:
                search_q = f"{project_name} {doc_title} mercado Brasil"
        except Exception:
            search_q = f"{project_name} {doc_title} mercado Brasil"

        await self._emit_progress(f"Gerando {doc_title}...", 40)

        # Pipeline no pool
        try:
            result = await self._run_in_pool(
                _worker_full_document_pipeline,
                self._api_key,
                prompt,
                None,  # Sem revisão para documentos personalizados
                [search_q],
                project_name,
                user_name,
                doc_type,
                doc_title,
            )
        except Exception as e:
            logger.error(f"[Marco] Erro no pipeline de {doc_title}: {e}")
            result = {
                "markdown": f"# {doc_title}\n\nErro ao gerar documento. Por favor, tente novamente.",
                "pdf_base64": None,
                "error": str(e),
            }

        await self._emit_progress(f"Finalizando {doc_title}...", 85)

        # Publica
        try:
            packet: dict = {
                "type": "document_ready",
                "doc_type": doc_type,
                "doc_title": doc_title,
                "plan": result.get("markdown", ""),
                "text": result.get("markdown", ""),
            }
            if doc_type == "execution_plan":
                packet["type"] = "execution_plan"
            await self._publish_packet(packet)
            await self._emit_progress(f"{doc_title} pronto! ✅", 100)
            logger.info(f"[Marco] {doc_title} publicado (Marketing only).")
        except Exception as e:
            logger.warning(f"[Marco] Erro ao publicar {doc_title}: {e}")

    # ──────────────────────────────────────────────────────────────────────
    # Guia de Órgão Público
    # ──────────────────────────────────────────────────────────────────────

    async def gerar_orientacao_orgao_publico(
        self,
        orgao_processo: str,
        contexto: str,
        user_name: str,
        project_name: str,
    ) -> None:
        """Gera guia de órgão público e publica no room."""
        logger.info(f"[Marco] Gerando guia: {orgao_processo} no ProcessPool...")
        self._blackboard.add_message("Sistema", f"Marco preparando guia sobre '{orgao_processo}'...")

        await self._emit_progress(f"Marco pesquisando sobre {orgao_processo}...", 15)

        from pdf_generator import ORIENTACAO_ORGAO_PROMPT

        full_transcript = self._blackboard.get_full_transcript()
        transcript_enriched = (
            f"Usuário: {user_name}\n"
            f"Projeto: {project_name}\n"
            f"Processo solicitado: {orgao_processo}\n"
            f"Contexto adicional: {contexto}\n"
            f"{{web_context}}\n\n"
            f"{full_transcript[:3000]}"
        )

        fmt_vars = {
            "transcript": transcript_enriched,
            "orgao_processo": orgao_processo,
            "projeto": project_name,
            "user_name": user_name,
        }
        try:
            prompt = ORIENTACAO_ORGAO_PROMPT.format(**fmt_vars)
        except KeyError as ke:
            logger.warning(f"[Marco] Chave ausente em ORIENTACAO_ORGAO_PROMPT: {ke}")
            prompt = ORIENTACAO_ORGAO_PROMPT.replace("{transcript}", transcript_enriched)

        search_queries = [
            f"{orgao_processo} Brasil 2024 passo a passo",
            f"{orgao_processo} custos taxas portais oficiais",
        ]

        await self._emit_progress(f"Elaborando guia: {orgao_processo}...", 50)

        try:
            result = await self._run_in_pool(
                _worker_full_document_pipeline,
                self._api_key,
                prompt,
                None,
                search_queries,
                project_name,
                user_name,
                "orientacao_orgao",
                f"Guia: {orgao_processo}",
                0.5,  # temperature mais baixa para guias
            )
        except Exception as e:
            logger.error(f"[Marco] Erro no pipeline de guia '{orgao_processo}': {e}")
            result = {
                "markdown": (
                    f"# Guia: {orgao_processo}\n\n"
                    f"Não foi possível gerar o guia completo neste momento. "
                    f"Por favor, consulte o portal gov.br para informações oficiais.\n\n"
                    f"**Link:** https://www.gov.br"
                ),
                "pdf_base64": None,
                "error": str(e),
            }

        # Publica
        try:
            packet: dict = {
                "type": "document_ready",
                "doc_type": "orientacao_orgao",
                "doc_title": f"Guia: {orgao_processo}",
                "plan": result.get("markdown", ""),
                "text": result.get("markdown", ""),
            }
            if result.get("pdf_base64"):
                packet["pdf_base64"] = result["pdf_base64"]
            await self._publish_packet(packet)
            await self._emit_progress(f"Guia pronto! ✅", 100)
            logger.info(f"[Marco] Guia '{orgao_processo}' publicado.")
        except Exception as e:
            logger.warning(f"[Marco] Erro ao publicar guia '{orgao_processo}': {e}")

    # ──────────────────────────────────────────────────────────────────────
    # Fallback estático (caso o LLM falhe completamente)
    # ──────────────────────────────────────────────────────────────────────

    def _generate_fallback_plan(self, user_name: str, project_name: str) -> str:
        """Gera documento Markdown secundário apenas se o LLM falhar."""
        from datetime import datetime
        now = datetime.now().strftime("%d/%m/%Y às %H:%M")

        transcript_lines = self._blackboard.transcript
        cfo_insights = [m["content"] for m in transcript_lines if "Carlos" in m.get("role", "")]
        legal_insights = [m["content"] for m in transcript_lines if "Daniel" in m.get("role", "")]
        cmo_insights = [m["content"] for m in transcript_lines if "Rodrigo" in m.get("role", "")]
        cto_insights = [m["content"] for m in transcript_lines if "Ana" in m.get("role", "")]
        user_messages = [m["content"] for m in transcript_lines if m.get("role") == "Usuário"]

        def fmt_insights(items: list) -> str:
            if not items:
                return "_Nenhuma análise registrada para esta área._"
            return "\n".join(f"- {item[:300]}" for item in items[:5])

        user_context = (
            "\n".join(f"- {u[:200]}" for u in user_messages[:10])
            if user_messages else "_Sem mensagens registradas._"
        )

        return f"""# 📋 Plano de Execução — Hive Mind

**Usuário:** {user_name}
**Sessão:** {project_name}
**Gerado em:** {now}

---

## 1. 🎯 Resumo Executivo

Esta sessão de mentoria reuniu um time completo de especialistas para analisar o projeto de **{user_name}** sob diferentes perspectivas: financeira, jurídica, marketing e tecnologia.

**Principais pontos levantados pelo usuário:**
{user_context}

---

## 2. 📊 Diagnóstico por Área

### 💰 Finanças — Carlos (CFO)
{fmt_insights(cfo_insights)}

### ⚖️ Jurídico — Daniel (Advogado)
{fmt_insights(legal_insights)}

### 📣 Marketing & Crescimento — Rodrigo (CMO)
{fmt_insights(cmo_insights)}

### 💻 Tecnologia & Produto — Ana (CTO)
{fmt_insights(cto_insights)}

---

## 3. 🚨 Prioridades Críticas

> As prioridades abaixo foram definidas com base nos temas discutidos durante a sessão.

1. **Validação do modelo de negócio** — Confirmar demanda real antes de qualquer investimento.
2. **Estrutura jurídica adequada** — Formalizar a empresa e proteger propriedade intelectual.
3. **Go-to-market enxuto** — Iniciar com um canal de aquisição principal, medir e escalar.
4. **MVP tecnológico** — Construir o mínimo viável para testar hipóteses com usuários reais.
5. **Fluxo de caixa positivo** — Garantir faturamento antes de escalar custos.

---

## 4. 📅 Cronograma Sugerido

- **30 dias:** Formalizar empresa, definir ICP e proposta de valor (Jurídico + Estratégia)
- **60 dias:** Lançar MVP ou versão beta, iniciar primeiras vendas (Produto + Vendas)
- **90 dias:** Validar unit economics - CAC, LTV - e ajustar pricing (Financeiro + Marketing)
- **6 meses:** Escalar canal principal de marketing (Growth + Operações)
- **12 meses:** Expandir produto/equipe, avaliar captação externa (Estratégia + Financeiro)

---

## 5. ⚠️ Riscos e Mitigações

- **Falta de tração com clientes:**
  - *Mitigação:* Validar antes de construir, fazer vendas manuais primeiro.
- **Burn rate elevado:**
  - *Mitigação:* Manter operação enxuta, priorizar receita sobre crescimento.
- **Problemas jurídicos futuros:**
  - *Mitigação:* Regularizar desde o início com suporte jurídico especializado.

---

## 6. ✅ Próximos Passos Imediatos (Esta Semana)

- [ ] Escrever a proposta de valor em 1 frase clara
- [ ] Identificar os 10 primeiros potenciais clientes para contato direto
- [ ] Escolher o modelo societário adequado (MEI, LTDA, etc.)
- [ ] Mapear os custos fixos e variáveis do negócio
- [ ] Definir o escopo mínimo do MVP e tecnologia necessária

---

## 7. 💬 Mensagem Final

*"{user_name}, você já deu o passo mais importante: buscou perspectivas diferentes e fez as perguntas certas. Agora é hora de executar com foco e disciplina. Lembre-se: os melhores negócios não nasceram perfeitos — foram construídos iteração por iteração. O time Hive Mind está aqui quando precisar!"*

— **Marco, Estrategista-Chefe · Hive Mind**

---

*Documento gerado automaticamente pela plataforma **Hive Mind** com base na sessão de mentoria realizada em {now}.*
"""
