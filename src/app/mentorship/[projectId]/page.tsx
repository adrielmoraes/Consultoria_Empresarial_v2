"use client";

import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Mic,
  MicOff,
  PhoneOff,
  TrendingUp,
  Gavel,
  Users,
  Code,
  Loader2,
  MessageSquare,
  Wifi,
  WifiOff,
  FileText,
  Star,
} from "lucide-react";
import {
  useState,
  useEffect,
  useRef,
  useCallback,
} from "react";
import { useParams, useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import {
  Room,
  RoomEvent,
  Track,
  Participant,
  RemoteParticipant,
  ConnectionState,
  DisconnectReason,
} from "livekit-client";

// ─── NextAuth type extension ──────────────────────────────────────────────────
// CORREÇÃO P3 / P8: estender o tipo da sessão para eliminar (as any).
// Defina também em types/next-auth.d.ts no seu projeto:
//
//   declare module "next-auth" {
//     interface Session {
//       user: { id: string; name?: string | null; email?: string | null };
//     }
//   }
//
// Aqui usamos uma interface local para tipagem interna do componente.
interface AuthUser {
  id: string;
  name?: string | null;
  email?: string | null;
}

// ─── Tipos e dados dos agentes ────────────────────────────────────────────────

type AgentInfo = {
  id: string;
  name: string;
  role: string;
  icon: React.ElementType;
  gradient: string;
  speaking: boolean;
};

const AGENTS_MAP: Record<string, Omit<AgentInfo, "speaking">> = {
  host: {
    id: "host",
    name: "Nathália",
    role: "Apresentadora",
    icon: Brain,
    gradient: "from-indigo-500 to-purple-600",
  },
  cfo: {
    id: "cfo",
    name: "Carlos",
    role: "CFO · Finanças",
    icon: TrendingUp,
    gradient: "from-emerald-500 to-teal-600",
  },
  legal: {
    id: "legal",
    name: "Daniel",
    role: "Advogado",
    icon: Gavel,
    gradient: "from-amber-500 to-orange-600",
  },
  cmo: {
    id: "cmo",
    name: "Rodrigo",
    role: "CMO · Marketing",
    icon: Users,
    gradient: "from-pink-500 to-rose-600",
  },
  cto: {
    id: "cto",
    name: "Ana",
    role: "CTO · Tecnologia",
    icon: Code,
    gradient: "from-blue-500 to-cyan-600",
  },
  plan: {
    id: "plan",
    name: "Marco",
    role: "Estrategista",
    icon: Star,
    gradient: "from-violet-500 to-fuchsia-600",
  },
};

const SPEAKER_COLORS: Record<string, string> = {
  Você: "text-white",
  Sistema: "text-gray-500",
  Nathália: "text-indigo-400",
  Carlos: "text-emerald-400",
  Daniel: "text-amber-400",
  Rodrigo: "text-pink-400",
  Ana: "text-blue-400",
  Marco: "text-violet-400",
};

function getSpeakerColor(speaker: string): string {
  for (const [key, color] of Object.entries(SPEAKER_COLORS)) {
    if (speaker.includes(key)) return color;
  }
  return "text-indigo-400";
}

type TranscriptMessage = {
  speaker: string;
  text: string;
  timestamp: string;
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(s: number): string {
  return `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60)
    .toString()
    .padStart(2, "0")}`;
}

async function safeFetch(url: string, options: RequestInit): Promise<Response> {
  // CORREÇÃO P4: wrapper que lança erro em respostas não-ok,
  // garantindo que os callers sempre tratem falhas de rede/HTTP.
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} em ${url}: ${body}`);
  }
  return res;
}

// ─── Página principal ─────────────────────────────────────────────────────────

export default function MentorshipRoomPage() {
  const params = useParams();
  const router = useRouter();
  const { data: session, status: authStatus } = useSession();
  const projectId = params.projectId as string;

  const [connectionState, setConnectionState] = useState<
    "connecting" | "connected" | "reconnecting" | "error"
  >("connecting");
  const [isMuted, setIsMuted] = useState(false);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [showEndConfirm, setShowEndConfirm] = useState(false);
  const [ending, setEnding] = useState(false);
  const [activeSpeakers, setActiveSpeakers] = useState<Set<string>>(new Set());
  const [transcript, setTranscript] = useState<TranscriptMessage[]>([]);
  const [showTranscript, setShowTranscript] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [executionPlan, setExecutionPlan] = useState<string | null>(null);
  const [showPlan, setShowPlan] = useState(false);

  const roomRef = useRef<Room | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  // CORREÇÃO P1 / P6: container de áudio dentro do componente, controlado
  // pelo React, em vez de injetar no document.body.
  const audioContainerRef = useRef<HTMLDivElement>(null);

  // Redireciona para login se não autenticado
  useEffect(() => {
    if (authStatus === "unauthenticated") router.replace("/login");
  }, [authStatus, router]);

  // CORREÇÃO P10: timer com deps vazias explícitas e cleanup garantido.
  useEffect(() => {
    const id = setInterval(() => setElapsedTime((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // Auto-scroll do transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  const addTranscriptMessage = useCallback((speaker: string, text: string) => {
    const timestamp = new Date().toLocaleTimeString("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
    });
    setTranscript((prev) => [...prev, { speaker, text, timestamp }]);
  }, []);

  // ─── Conexão LiveKit ────────────────────────────────────────────────────────
  //
  // CORREÇÃO P2: a lógica de conexão fica inline no useEffect, com flag
  // `cancelled` que descarta a sala se o efeito for limpo antes do connect
  // terminar (Strict Mode monta 2x em dev; flag previne dupla conexão).
  //
  // CORREÇÃO P5: sem useCallback para connectToRoom — deps ficam naturalmente
  // corretas porque a função lê tudo do closure do efeito.

  useEffect(() => {
    if (authStatus !== "authenticated" || !session?.user) return;

    // CORREÇÃO P3 / P8: acesso tipado via AuthUser, sem cast (as any)
    const user = session.user as AuthUser;
    const userId = user.id;
    const userName = user.name ?? "Usuário";

    let cancelled = false;
    let room: Room | null = null;

    async function connect() {
      try {
        // Cria a sessão de mentoria no backend
        const sessionRes = await safeFetch("/api/sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ projectId, userId }),
        });
        if (cancelled) return;
        const { sessionId: sid, roomName } = await sessionRes.json();
        setSessionId(sid);

        // Obtém token LiveKit
        const tokenRes = await safeFetch("/api/livekit/token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            roomName,
            participantName: userName,
            participantIdentity: `user-${userId}`,
          }),
        });
        if (cancelled) return;
        const { token, url } = await tokenRes.json();

        // Configura a sala
        room = new Room({
          adaptiveStream: true,
          dynacast: true,
          // CORREÇÃO P9: política de reconexão automática em quedas transitórias
          reconnectPolicy: {
            maxRetryDelay: 5000,
            retryDelayIncrease: 1000,
            maxRetries: 5,
          },
          audioCaptureDefaults: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });

        // ── Eventos da sala ──────────────────────────────────────────────────

        room.on(RoomEvent.Connected, async () => {
          if (cancelled) { room?.disconnect(); return; }
          roomRef.current = room;
          setConnectionState("connected");
          addTranscriptMessage("Sistema", "Conectado. Aguardando os especialistas...");
          try {
            await room!.localParticipant.setMicrophoneEnabled(true);
          } catch (micErr) {
            console.warn("[LiveKit] Erro ao ativar microfone:", micErr);
          }
        });

        // CORREÇÃO P9: distingue desconexão intencional de falha de rede
        room.on(RoomEvent.Disconnected, (reason?: DisconnectReason) => {
          if (reason === DisconnectReason.CLIENT_INITIATED) return;
          setConnectionState("error");
          addTranscriptMessage("Sistema", "Conexão perdida. Recarregue a página para reconectar.");
        });

        // CORREÇÃO P9: eventos de reconexão automática do SDK
        room.on(RoomEvent.Reconnecting, () => {
          setConnectionState("reconnecting");
          addTranscriptMessage("Sistema", "Reconectando...");
        });

        room.on(RoomEvent.Reconnected, () => {
          setConnectionState("connected");
          addTranscriptMessage("Sistema", "Reconectado com sucesso.");
        });

        // CORREÇÃO P1 / P6: elementos de áudio vão para o container ref,
        // não para document.body.
        room.on(
          RoomEvent.TrackSubscribed,
          (track, _pub, participant: RemoteParticipant) => {
            if (track.kind === Track.Kind.Audio && audioContainerRef.current) {
              // Remove elemento anterior do mesmo participante, se existir
              audioContainerRef.current
                .querySelector(`#audio-${participant.identity}`)
                ?.remove();

              const el = track.attach() as HTMLAudioElement;
              el.id = `audio-${participant.identity}`;
              el.autoplay = true;
              audioContainerRef.current.appendChild(el);
            }
          }
        );

        room.on(
          RoomEvent.TrackUnsubscribed,
          (track, _pub, participant: RemoteParticipant) => {
            audioContainerRef.current
              ?.querySelector(`#audio-${participant.identity}`)
              ?.remove();
            track.detach();
          }
        );

        room.on(
          RoomEvent.ActiveSpeakersChanged,
          (speakers: Participant[]) => {
            const ids = new Set(
              speakers.map((s) => {
                const id = s.identity;
                if (id.startsWith("agent-")) return id.replace("agent-", "");
                if (id.startsWith("user-")) return "user";
                return id;
              })
            );
            setActiveSpeakers(ids);
          }
        );

        room.on(
          RoomEvent.DataReceived,
          (payload: Uint8Array, participant?: RemoteParticipant) => {
            try {
              const data = JSON.parse(new TextDecoder().decode(payload));

              if (data.type === "transcript") {
                addTranscriptMessage(data.speaker, data.text);
              } else if (data.type === "execution_plan") {
                setExecutionPlan(data.plan ?? data.text ?? "");
                setShowPlan(true);
                addTranscriptMessage(
                  "Marco (Estrategista)",
                  "Plano de Execução gerado! Veja o painel lateral."
                );
              } else if (data.type === "session_end") {
                handleSessionCompleted(data.transcript);
              }
            } catch {
              // payload malformado — ignorar silenciosamente
            }
          }
        );

        room.on(
          RoomEvent.ParticipantConnected,
          (participant: RemoteParticipant) => {
            const id = participant.identity;
            if (id.startsWith("agent-")) {
              const agentId = id.replace("agent-", "");
              const agent = AGENTS_MAP[agentId];
              if (agent) {
                addTranscriptMessage(
                  "Sistema",
                  `${agent.name} (${agent.role}) entrou na sessão.`
                );
              }
            }
          }
        );

        if (!cancelled) await room.connect(url, token);
        else room.disconnect();

      } catch (error) {
        if (cancelled) return;
        console.error("[LiveKit] Erro ao conectar:", error);
        setConnectionState("error");
        addTranscriptMessage(
          "Sistema",
          "Erro ao conectar. Verifique sua conexão e recarregue a página."
        );
      }
    }

    connect();

    // CORREÇÃO P2: cleanup com flag cancelled previne uso da sala após unmount.
    // CORREÇÃO P1: remove todos os elementos de áudio ao desmontar.
    return () => {
      cancelled = true;
      room?.disconnect();
      roomRef.current = null;
      audioContainerRef.current
        ?.querySelectorAll("audio")
        .forEach((el) => el.remove());
    };
  }, [authStatus, session, projectId, addTranscriptMessage]);

  // ─── Handlers ───────────────────────────────────────────────────────────────

  const toggleMute = async () => {
    const lp = roomRef.current?.localParticipant;
    if (!lp) return;
    await lp.setMicrophoneEnabled(isMuted);
    setIsMuted((m) => !m);
  };

  // CORREÇÃO P4: usa safeFetch — erros de HTTP são logados e não engolidos.
  const handleEndSession = async () => {
    setEnding(true);
    try {
      if (
        roomRef.current &&
        roomRef.current.state === ConnectionState.Connected
      ) {
        try {
          const data = new TextEncoder().encode(
            JSON.stringify({ type: "end_session" })
          );
          await roomRef.current.localParticipant.publishData(data, {
            reliable: true,
          });
          await new Promise((r) => setTimeout(r, 1000));
        } catch {
          // best-effort — não bloqueia o encerramento
        }
      }

      if (sessionId) {
        const fullTranscript = transcript
          .map((m) => `[${m.speaker}]: ${m.text}`)
          .join("\n");
        try {
          await safeFetch("/api/sessions/finalize", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              sessionId,
              transcript: fullTranscript,
              markdownContent: executionPlan ?? null,
            }),
          });
        } catch (err) {
          console.error("[Sessão] Falha ao finalizar:", err);
          // Não bloqueia o redirect — o usuário não deve ficar preso na sala
        }
      }

      await roomRef.current?.disconnect();
      router.push("/dashboard");
    } catch {
      setEnding(false);
      router.push("/dashboard");
    }
  };

  // CORREÇÃO P4: mesma aplicação de safeFetch aqui.
  const handleSessionCompleted = useCallback(
    async (fullTranscript?: string) => {
      if (sessionId) {
        const text =
          fullTranscript ??
          transcript.map((m) => `[${m.speaker}]: ${m.text}`).join("\n");
        try {
          await safeFetch("/api/sessions/finalize", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              sessionId,
              transcript: text,
              markdownContent: executionPlan ?? null,
            }),
          });
        } catch (err) {
          console.error("[Sessão] Falha ao finalizar automaticamente:", err);
        }
      }
      roomRef.current?.disconnect();
      router.push("/dashboard");
    },
    [sessionId, transcript, executionPlan, router]
  );

  // ─── Guards de render ────────────────────────────────────────────────────────

  if (authStatus === "loading") {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-950">
        <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
      </div>
    );
  }

  if (authStatus === "unauthenticated") return null;

  const agents = Object.values(AGENTS_MAP).map((a) => ({
    ...a,
    speaking: activeSpeakers.has(a.id),
  }));

  const connectionIcon = {
    connected: <Wifi className="w-3.5 h-3.5 text-emerald-400" />,
    connecting: <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />,
    reconnecting: <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />,
    error: <WifiOff className="w-3.5 h-3.5 text-red-400" />,
  }[connectionState];

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="h-screen flex flex-col bg-gray-950">
      {/*
        CORREÇÃO P1 / P6: container oculto para elementos de áudio.
        Fica dentro da árvore React → cleanup garantido no unmount.
      */}
      <div ref={audioContainerRef} className="hidden" aria-hidden="true" />

      {/* Top Bar */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-900/80 backdrop-blur-sm border-b border-white/5 shrink-0">
        <div className="flex items-center gap-3">
          <div className="bg-gradient-to-r from-indigo-500 to-purple-600 p-1.5 rounded-lg">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-white">Sala de Mentoria</h1>
            <p className="text-xs text-gray-400">6 especialistas • Sessão ao vivo</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {connectionIcon}

          {/* Badge de reconexão */}
          {connectionState === "reconnecting" && (
            <span className="text-[10px] text-amber-400 font-medium">
              Reconectando...
            </span>
          )}

          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            <span className="text-sm text-gray-400 font-mono">
              {formatTime(elapsedTime)}
            </span>
          </div>

          {executionPlan && (
            <button
              onClick={() => setShowPlan((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                showPlan
                  ? "bg-violet-500/20 text-violet-300 border border-violet-500/30"
                  : "bg-white/5 text-gray-400 hover:text-white"
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              Plano
            </button>
          )}

          <button
            onClick={() => setShowTranscript((v) => !v)}
            className={`p-2 rounded-lg transition-colors ${
              showTranscript
                ? "bg-indigo-500/20 text-indigo-400"
                : "bg-white/5 text-gray-400 hover:text-white"
            }`}
          >
            <MessageSquare className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Main */}
      <div className="flex-1 flex overflow-hidden">
        {/* Agents Grid */}
        <div className="flex-1 p-3 sm:p-4 overflow-hidden">
          <div className="hidden md:grid grid-cols-3 grid-rows-2 gap-3 h-full">
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
          <div className="md:hidden grid grid-cols-2 gap-3">
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} compact />
            ))}
          </div>
        </div>

        {/* Execution Plan Panel */}
        <AnimatePresence>
          {showPlan && executionPlan && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 380, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              className="bg-gray-900/90 border-l border-violet-500/20 flex flex-col overflow-hidden shrink-0"
            >
              <div className="p-4 border-b border-white/5 flex items-center gap-2">
                <Star className="w-4 h-4 text-violet-400 shrink-0" />
                <div>
                  <h3 className="text-sm font-semibold text-white">
                    Plano de Execução
                  </h3>
                  <p className="text-xs text-gray-500 mt-0.5">
                    por Marco – Estrategista Chefe
                  </p>
                </div>
              </div>

              {/*
                CORREÇÃO P7: renderer de markdown sem dependências externas.
                Trata h1/h2/h3, listas ordenadas e não-ordenadas, listas
                aninhadas, negrito, itálico, código inline, blocos de código,
                separadores e parágrafos — sem precisar de react-markdown.
              */}
              <div className="flex-1 overflow-y-auto p-4">
                <MarkdownRenderer content={executionPlan} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Transcript Panel */}
        <AnimatePresence>
          {showTranscript && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 340, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              className="bg-gray-900/80 border-l border-white/5 flex flex-col overflow-hidden shrink-0"
            >
              <div className="p-4 border-b border-white/5">
                <h3 className="text-sm font-semibold text-white">Transcrição</h3>
                <p className="text-xs text-gray-500">{transcript.length} mensagens</p>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {transcript.map((msg, i) => (
                  <div key={i}>
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={`text-xs font-semibold ${getSpeakerColor(
                          msg.speaker
                        )}`}
                      >
                        {msg.speaker}
                      </span>
                      <span className="text-[10px] text-gray-600">
                        {msg.timestamp}
                      </span>
                    </div>
                    <p className="text-gray-300 text-xs leading-relaxed">
                      {msg.text}
                    </p>
                  </div>
                ))}
                <div ref={transcriptEndRef} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Controls Bar */}
      <div className="flex items-center justify-center gap-4 px-4 py-4 bg-gray-900/80 backdrop-blur-sm border-t border-white/5 shrink-0">
        <motion.button
          whileTap={{ scale: 0.9 }}
          onClick={toggleMute}
          className={`w-12 h-12 rounded-full flex items-center justify-center transition-all ${
            isMuted
              ? "bg-red-500/20 border border-red-500/50 text-red-400"
              : "bg-white/10 border border-white/10 text-white hover:bg-white/20"
          }`}
          title={isMuted ? "Ativar microfone" : "Silenciar microfone"}
        >
          {isMuted ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
        </motion.button>

        <motion.button
          whileTap={{ scale: 0.9 }}
          onClick={() => setShowEndConfirm(true)}
          className="w-14 h-12 rounded-full bg-red-500 hover:bg-red-600 text-white flex items-center justify-center transition-all"
          title="Encerrar sessão"
        >
          <PhoneOff className="w-5 h-5" />
        </motion.button>
      </div>

      {/* End Confirmation Modal */}
      <AnimatePresence>
        {showEndConfirm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4"
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-gray-900 border border-white/10 rounded-2xl p-8 max-w-md w-full text-center shadow-2xl"
            >
              <div className="w-16 h-16 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center mx-auto mb-4">
                <PhoneOff className="w-8 h-8 text-red-400" />
              </div>
              <h2 className="text-xl font-bold text-white mb-2">
                Encerrar Mentoria?
              </h2>
              <p className="text-sm text-gray-400 mb-6">
                Ao encerrar, o Plano de Execução completo será gerado pelo Marco
                e salvo no seu Dashboard.
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => setShowEndConfirm(false)}
                  className="flex-1 px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-gray-300 hover:bg-white/10 transition-colors text-sm"
                  disabled={ending}
                >
                  Continuar
                </button>
                <button
                  onClick={handleEndSession}
                  disabled={ending}
                  className="flex-1 px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white transition-colors text-sm flex items-center justify-center gap-2"
                >
                  {ending ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Encerrando...
                    </>
                  ) : (
                    "Encerrar"
                  )}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── MarkdownRenderer ─────────────────────────────────────────────────────────
// Renderer de markdown sem dependências externas.
// Suporta: h1–h3, negrito, itálico, código inline, blocos de código,
// listas ordenadas e não-ordenadas (com aninhamento), separadores e parágrafos.

type MdToken =
  | { type: "h1" | "h2" | "h3"; text: string }
  | { type: "hr" }
  | { type: "code_block"; lang: string; code: string }
  | { type: "ul"; items: MdListItem[] }
  | { type: "ol"; items: MdListItem[] }
  | { type: "p"; text: string }
  | { type: "blank" };

type MdListItem = { text: string; depth: number; ordered: boolean; index: number };

function parseInline(text: string): React.ReactNode[] {
  // Processa **negrito**, *itálico* e `código inline`
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**"))
      return <strong key={i} className="text-white font-semibold">{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*"))
      return <em key={i} className="text-gray-300 italic">{part.slice(1, -1)}</em>;
    if (part.startsWith("`") && part.endsWith("`"))
      return <code key={i} className="text-violet-300 bg-violet-950/50 rounded px-1 text-[11px] font-mono">{part.slice(1, -1)}</code>;
    return part;
  });
}

function tokenize(content: string): MdToken[] {
  const lines = content.split("\n");
  const tokens: MdToken[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Blocos de código cercados por ```
    if (line.trim().startsWith("```")) {
      const lang = line.trim().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      tokens.push({ type: "code_block", lang, code: codeLines.join("\n") });
      i++;
      continue;
    }

    // Headings
    const h3 = line.match(/^### (.+)/);
    const h2 = line.match(/^## (.+)/);
    const h1 = line.match(/^# (.+)/);
    if (h3) { tokens.push({ type: "h3", text: h3[1] }); i++; continue; }
    if (h2) { tokens.push({ type: "h2", text: h2[1] }); i++; continue; }
    if (h1) { tokens.push({ type: "h1", text: h1[1] }); i++; continue; }

    // Separador
    if (/^---+$/.test(line.trim())) { tokens.push({ type: "hr" }); i++; continue; }

    // Listas (ordenadas e não-ordenadas, com aninhamento por indentação)
    const ulMatch = line.match(/^(\s*)[*\-+] (.+)/);
    const olMatch = line.match(/^(\s*)(\d+)\. (.+)/);
    if (ulMatch || olMatch) {
      const items: MdListItem[] = [];
      let topOrdered = !!olMatch;
      while (i < lines.length) {
        const l = lines[i];
        const ul = l.match(/^(\s*)[*\-+] (.+)/);
        const ol = l.match(/^(\s*)(\d+)\. (.+)/);
        if (ul) {
          items.push({ text: ul[2], depth: ul[1].length, ordered: false, index: 0 });
          i++;
        } else if (ol) {
          items.push({ text: ol[3], depth: ol[1].length, ordered: true, index: parseInt(ol[2]) });
          i++;
        } else {
          break;
        }
      }
      tokens.push({ type: topOrdered ? "ol" : "ul", items });
      continue;
    }

    // Linha em branco
    if (!line.trim()) { tokens.push({ type: "blank" }); i++; continue; }

    // Parágrafo
    tokens.push({ type: "p", text: line }); i++;
  }

  return tokens;
}

function renderListItems(items: MdListItem[]): React.ReactNode {
  // Agrupa itens em listas aninhadas recursivamente
  const result: React.ReactNode[] = [];
  let j = 0;
  while (j < items.length) {
    const item = items[j];
    const children: MdListItem[] = [];
    j++;
    while (j < items.length && items[j].depth > item.depth) {
      children.push(items[j]);
      j++;
    }
    result.push(
      <li key={j} className="text-gray-300 text-xs my-0.5">
        <span>{parseInline(item.text)}</span>
        {children.length > 0 && (
          item.ordered
            ? <ol className="list-decimal pl-4 mt-1">{renderListItems(children)}</ol>
            : <ul className="list-disc pl-4 mt-1">{renderListItems(children)}</ul>
        )}
      </li>
    );
  }
  return <>{result}</>;
}

function MarkdownRenderer({ content }: { content: string }) {
  const tokens = tokenize(content);

  return (
    <div className="space-y-1">
      {tokens.map((tok, i) => {
        switch (tok.type) {
          case "h1":
            return <h1 key={i} className="text-white font-bold text-sm mt-4 mb-1 first:mt-0">{parseInline(tok.text)}</h1>;
          case "h2":
            return <h2 key={i} className="text-violet-300 font-semibold text-xs mt-3 mb-1 first:mt-0">{parseInline(tok.text)}</h2>;
          case "h3":
            return <h3 key={i} className="text-gray-200 font-medium text-xs mt-2 mb-0.5">{parseInline(tok.text)}</h3>;
          case "hr":
            return <hr key={i} className="border-white/10 my-3" />;
          case "code_block":
            return (
              <pre key={i} className="bg-gray-950 border border-white/10 rounded-lg p-3 overflow-x-auto my-2">
                <code className="text-violet-300 text-[11px] font-mono">{tok.code}</code>
              </pre>
            );
          case "ul":
            return (
              <ul key={i} className="list-disc pl-4 my-1">
                {renderListItems(tok.items)}
              </ul>
            );
          case "ol":
            return (
              <ol key={i} className="list-decimal pl-4 my-1">
                {renderListItems(tok.items)}
              </ol>
            );
          case "p":
            return <p key={i} className="text-gray-400 text-xs leading-relaxed">{parseInline(tok.text)}</p>;
          case "blank":
            return <div key={i} className="h-1" />;
          default:
            return null;
        }
      })}
    </div>
  );
}

// ─── AgentCard ────────────────────────────────────────────────────────────────

function AgentCard({
  agent,
  compact = false,
}: {
  agent: AgentInfo;
  compact?: boolean;
}) {
  const Icon = agent.icon;

  return (
    <motion.div
      layout
      className={`relative rounded-2xl overflow-hidden border-2 transition-all duration-500 ${
        compact ? "h-40" : "h-full"
      } ${
        agent.speaking
          ? "border-indigo-500/70 shadow-lg shadow-indigo-500/20"
          : "border-white/5 hover:border-white/10"
      }`}
    >
      <div
        className={`absolute inset-0 bg-gradient-to-br ${agent.gradient} opacity-10`}
      />
      <div className="absolute inset-0 bg-gray-900/70" />

      {/* Avatar */}
      <div className="absolute inset-0 flex items-center justify-center">
        <motion.div
          animate={
            agent.speaking
              ? { scale: [1, 1.1, 1], opacity: [0.6, 1, 0.6] }
              : { scale: 1, opacity: 0.35 }
          }
          transition={
            agent.speaking
              ? { duration: 1.2, repeat: Infinity, ease: "easeInOut" }
              : {}
          }
          className={`${
            compact ? "w-14 h-14" : "w-20 h-20 sm:w-24 sm:h-24"
          } rounded-full bg-gradient-to-r ${agent.gradient} flex items-center justify-center`}
        >
          <Icon
            className={`${
              compact ? "w-7 h-7" : "w-10 h-10 sm:w-12 sm:h-12"
            } text-white`}
          />
        </motion.div>
      </div>

      {/* Speaking indicator */}
      {agent.speaking && (
        <div className="absolute top-3 right-3">
          <div className="flex items-center gap-1.5 bg-indigo-500/20 border border-indigo-500/30 rounded-full px-2 py-1">
            <div className="flex items-center gap-0.5">
              {[0, 1, 2].map((i) => (
                <motion.div
                  key={i}
                  animate={{ height: ["4px", "14px", "4px"] }}
                  transition={{
                    duration: 0.5,
                    repeat: Infinity,
                    delay: i * 0.12,
                  }}
                  className="w-[3px] bg-indigo-400 rounded-full"
                />
              ))}
            </div>
            <span className="text-[10px] text-indigo-300 font-medium">
              Falando
            </span>
          </div>
        </div>
      )}

      {/* Name badge */}
      <div className="absolute bottom-0 left-0 right-0 p-3 bg-gradient-to-t from-black/80 to-transparent">
        <p
          className={`font-semibold text-white ${
            compact ? "text-xs" : "text-sm"
          }`}
        >
          {agent.name}
        </p>
        <p className={`text-gray-300 ${compact ? "text-[10px]" : "text-xs"}`}>
          {agent.role}
        </p>
      </div>
    </motion.div>
  );
}