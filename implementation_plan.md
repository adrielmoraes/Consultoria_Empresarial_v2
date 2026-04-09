# Modo Mentoria Multijogador + Handover Padrão Peer-to-Peer + Transferência Lateral

Este plano detalha: (1) A arquitetura "Guest" multijogador; (2) Conversação contínua do Especialista; (3) Transferência direta entre Especialistas sem intermediários; **(4) [NOVO] Handover Narrado (Passando a Bola)**.

## User Review Required

> [!WARNING]  
> **Comportamento do Grid Visual:** Adicionar de 1 a 3 convidados + 5 agentes resultará em um grid mais robusto (até 9 cards). O CSS adaptará as faces flexivelmente pela tela.
>
> **Fluxo de Devolução (Prioridade da Nathália vs Transferência Lateral):** A regra primária no Cérebro dos Agentes será mantida para que a devolução sem rumo volte à Nathália como apresentadora. A Transferência Lateral Direta e Falada será restrita às dúvidas estritas da área coligada. Você nos aprova para ir ao código com este documento finalizado?

## Proposed Changes

---

### 1. Novo Fluxo de Conversação (Peer-to-Peer & Lateral Handover)

#### [MODIFY] `agents/worker.py` (Lógica e Tools dos Agentes)
- **Especialistas Livres (Loop Infinito):** Deixam de devolver a palavra em 1 turno. Conversam até saturar o tema.
- **Delegação Principal (`devolver_para_nathalia`):** O Especialista encerra e acorda a Nathália.

- **Transferência Direta Narrada (`transferir_para_especialista(alvo, contexto)`):**
  - **Dinâmica Vocal:** Quando o Carlos diagnosticar necessidade de chamar o Daniel, nós forçaremos no Prompt base que o Carlos **fale em voz alta primeiro**: *"Vou acionar o Daniel do Jurídico para responder a essa questão do contrato."*
  - **Injeção de Contexto (O Pulo de Gato):** Após ele falar, a ferramenta vai registrar não apenas o pedido de ativação pro Daniel, mas o Argumento de Contexto cruzado (Ex: *"O usuário quer saber como fica a divisão societária no contrato"*). 
  - **Acesso Quente:** O LiveKit ativará instantaneamente o áudio do Daniel, e nós injetaremos no contexto dele: *"Carlos acabou de transferir a palavra para você com esta solicitação: [contexto]. Inicie sua fala concordando com o Carlos e já passando a visão do Daniel para o usuário."*
  - **Resultado na Reunião:** Daniel em voz sintética dirá: *"Obrigado Carlos. Exatamente, usuário. Sobre os contratos..."* -> Isso vai gerar aquele efeito assombroso de reunião real com múltiplos diretores conversando entre si sobre as dores do cliente!

#### [MODIFY] Instruções Globais e Prompts
- Enriquecer as regras no `worker.py` para reforçar a transição oral entre as intersecções dos IAs.

---

### 2. Frontend - Componentes Multijogador

#### [MODIFY] `src/app/mentorship/[projectId]/page.tsx`
- Grid Flexível redimensionando Avatares Humanos (`user-*`, `guest-*`) e Agentes.
- Status Visual de Quem detém o Token.
- Botão "Pausar IA" ou "Silenciar Mesa": para abafar as IAs quando os humanos forem ter discussões acaloradas.
- Botão "👥 Convidar Equipe".

#### [NEW] Lobby Público & Ambiente de Guest (`src/app/join` e `guest`)
- Salas de participação read-only sem edição de projeto.

---

### 3. Backend e Tokens Restritos

#### [NEW] `src/app/api/livekit/guest-token/route.ts`
- Novo endpoint para gerar entrada LiveKit restrita a convidados do Host atual (canPublish, canSubscribe).

## Verification Plan

### Testes Manuais de Handover
1. O Host interage com Carlos perguntando custos da plataforma. O Carlos responde.
2. O Host fala: *"Carlos, E sobre o contrato que rege esses pagamentos? Dá pra consultar o nosso jurídico?"*
3. O Carlos fala no microfone: *"Com certeza, vou repassar essa dúvida ao Daniel."*
4. O Carlos aciona o Código que desliga o próprio microfone, repassa o contexto ao Daniel e desperta o Daniel.
5. O Daniel fala no microfone: *"Isso mesmo Carlos. Pessoal, sobre os contratos, seria o seguinte..."*
