# Mentoria AI – Plataforma Multi-Agentes de Mentoria Empresarial

## Overview
A multi-agent AI business mentorship platform built with Next.js and Python LiveKit workers. Six specialized AI agents collaborate in real-time via voice to help entrepreneurs develop their projects, culminating in a detailed execution plan.

## Architecture

### Frontend (Next.js)
- **Runtime**: Node.js 20, Next.js 14 (App Router), TypeScript, Tailwind CSS
- **Port**: 5000 (mapped to external port 80)
- **Auth**: NextAuth.js with JWT sessions
- **Database**: PostgreSQL via Drizzle ORM
- **Payments**: Stripe integration
- **Real-time**: LiveKit Client SDK for room management

### Backend Agent Worker (Python)
- **Runtime**: Python 3.12 with packages in `.pythonlibs/`
- **Framework**: `livekit-agents==1.4.6`
- **LLM**: `google.realtime.RealtimeModel` (Gemini Live) for Host (Nathália) — handles STT+LLM+TTS+VAD
- **Specialist TTS**: `google.genai` SDK → Gemini TTS API (`gemini-2.5-flash-preview-tts`)
- **Voices**: Aoede (Nathália), Charon (Carlos), Fenrir (Daniel), Puck (Rodrigo), Kore (Ana), Zephyr (Marco)
- **VAD**: Silero (via `livekit-plugins-silero`)

### The 6 Agents
| Agent | Role | Voice |
|-------|------|-------|
| Nathália | Host/Apresentadora | Aoede |
| Carlos | CFO · Finanças | Charon |
| Daniel | Advogado | Fenrir |
| Rodrigo | CMO · Marketing | Puck |
| Ana | CTO · Tecnologia | Kore |
| Marco | Estrategista/Planner | Zephyr |

## Workflows
- **Start application**: `npm run dev` (port 5000, webview)
- **Start agent worker**: `python3 agents/worker.py start` (console)

## Key Files
- `agents/worker.py` — Python multi-agent LiveKit worker
- `agents/pdf_generator.py` — Execution plan PDF generator
- `src/app/mentorship/[projectId]/page.tsx` — Mentorship room UI (6 agents + transcript + plan)
- `src/app/api/sessions/route.ts` — Creates LiveKit room + session in DB
- `src/app/api/sessions/finalize/route.ts` — Finalizes session, saves execution plan
- `src/app/api/livekit/token/route.ts` — Generates LiveKit access tokens
- `src/lib/db/schema.ts` — Database schema
- `src/lib/livekit.ts` — LiveKit token generation utility

## Environment Variables (Secrets)
- `AUTH_SECRET` — NextAuth.js session secret
- `LIVEKIT_API_KEY` — LiveKit API key
- `LIVEKIT_API_SECRET` — LiveKit API secret
- `LIVEKIT_URL` — LiveKit server WebSocket URL (used by both Next.js and the Python worker)
- `NEXT_PUBLIC_LIVEKIT_URL` — LiveKit server WebSocket URL (public, for the browser client)
- `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` — Stripe publishable key
- `STRIPE_SECRET_KEY` — Stripe secret key
- `STRIPE_WEBHOOK_SECRET` — Stripe webhook secret
- `GEMINI_API_KEY` — Google Gemini API key
- `DATABASE_URL` — PostgreSQL connection string (provided automatically by Replit)

## Replit Setup Notes
- Python packages installed to `.pythonlibs/` via `pip install --user`
- `next.config.ts` uses `process.env.REPLIT_DEV_DOMAIN` to allow HMR through the Replit proxy
- Both workflows run in parallel under the "Project" run button

## Agent Communication Flow
1. User joins room → LiveKit worker picks up job
2. Nathália (Host) greets and gathers project context
3. Nathália calls function tools to invoke specialists
4. Each specialist generates response via Gemini LLM, speaks via Gemini TTS
5. All specialists connect to room with separate identities (distinct participants)
6. Transcript published via room data events to frontend
7. When user ends session, Marco generates full Execution Plan
8. Plan shown in frontend sidebar + saved to database

## Blackboard Pattern
All agents share a `Blackboard` Python object that accumulates:
- Project name and user query
- Full conversation transcript
- Individual specialist responses

## Language
All agents speak Brazilian Portuguese (pt-BR).

## Bug Fixes Applied (April 2026)

### Specialist Premature Handoff Fix
**Root cause**: `devolver_para_nathalia` called `get_last_user_message()` on the ENTIRE transcript,
including stale messages from Nathália's conversation (e.g., "entendi"). If the user said "entendi"
to Nathália before the specialist was activated, the very first `devolver_para_nathalia` call would
see it and immediately approve the handoff — causing the specialist to exit after just one reply.

**Fixes applied to `agents/worker.py`**:

1. **Module-level transcript helpers** — `_extract_transcribed_text`, `_should_ignore_user_transcript`
   extracted to module scope so both `_start_specialist_in_room` and `_run_entrypoint` share them
   without duplication or NameErrors.

2. **`SpecialistAgent._activation_transcript_len`** — new field set to `len(blackboard.transcript)`
   at the moment of activation in `_handle_activation`. All handoff checks now only consider
   messages at indices `>= _activation_transcript_len`.

3. **`SpecialistAgent._user_messages_since_activation`** — counter reset to 0 on each activation,
   incremented when a real (non-noise) user utterance is received. Acts as a minimum-turns gate.

4. **`devolver_para_nathalia` guards**:
   - Guard 1: Blocks if `_user_messages_since_activation < 1` (user hasn't spoken yet).
   - Guard 2: Reads only `transcript[_activation_transcript_len:]` for handoff intent, not the
     full history. Returns "CONTINUE_COM_USUARIO" if last new user message doesn't confirm done.

5. **`transferir_para_especialista` guard** — same minimum-turns check applied.

6. **`classify_user_handoff_intent` hardened** — removed ambiguous "entendi" alone (user may say
   "entendi, mas..." and still have questions). Only unambiguous multi-word phrases trigger handoff.

7. **Activation prompts** — both `from_agent` and Nathália activation prompts now explicitly list
   the exact phrases the user must say to trigger handoff and note that the tool auto-blocks early
   calls.

8. **Specialist system prompts** — all four specialist prompts updated with the exact exit phrases
   and the auto-blocking note.
