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
  Paperclip,
  UploadCloud,
  CheckCircle2,
  AlertCircle
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
  DefaultReconnectPolicy,
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
    gradient: "from-[#d4af37] to-[#b08d24]",
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
  // Marco (Estrategista) opera nos bastidores — não aparece na tela principal
};

const SPEAKER_COLORS: Record<string, string> = {
  Você: "text-white",
  Sistema: "text-gray-500",
  Nathália: "text-[#d4af37]",
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
  return "text-[#d4af37]";
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
  const [showPlan, setShowPlan] = useState<boolean | "content" | "checklist">(false);

  // F4: Timeout de connecting
  const [connectingTooLong, setConnectingTooLong] = useState(false);
  const [connectingTimedOut, setConnectingTimedOut] = useState(false);

  // F5: Document / Knowledge Upload
  const [showUpload, setShowUpload] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [docs, setDocs] = useState<{id: string, fileName: string, createdAt: string}[]>([]);

  // F5: Status individual dos agentes conectados
  const [connectedAgents, setConnectedAgents] = useState<Set<string>>(new Set());

  const roomRef = useRef<Room | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const sessionCreatingRef = useRef(false);

  // CORREÇÃO P1 / P6: container de áudio dentro do componente, controlado
  // pelo React, em vez de injetar no document.body.
  const audioContainerRef = useRef<HTMLDivElement>(null);

  // Refs para gerenciar estado de conexão
  const connectionStartedRef = useRef(false);
  const isReconnectingRef = useRef(false);
  const sessionDataRef = useRef<{
    sessionId?: string;
    roomName?: string;
    token?: string;
    url?: string;
    userId?: string;
  } | null>(null);

  // Redireciona para login se não autenticado (executa apenas quando authStatus muda)
  useEffect(() => {
    if (authStatus === "unauthenticated") {
      router.replace("/login");
    }
  }, [authStatus]);

  // Carregar lista inicial de documentos
  useEffect(() => {
    if (projectId) {
      fetch(`/api/projects/${projectId}/documents`)
        .then(res => res.json())
        .then(data => {
          if (Array.isArray(data)) setDocs(data);
        })
        .catch(err => console.error("Erro ao carregar documentos:", err));
    }
  }, [projectId]);

  // Timer (executa apenas uma vez na montagem)
  useEffect(() => {
    const id = setInterval(() => setElapsedTime((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // F4: Timeout de connecting — aviso visual após 15s, retry após 60s
  useEffect(() => {
    if (connectionState !== "connecting") {
      setConnectingTooLong(false);
      setConnectingTimedOut(false);
      return;
    }

    const timer15s = setTimeout(() => {
      setConnectingTooLong(true);
      console.log("[Room] Connecting por mais de 15s...");
    }, 15_000);

    const timer60s = setTimeout(() => {
      setConnectingTimedOut(true);
      console.warn("[Room] Connecting por mais de 60s — timeout.");
    }, 60_000);

    return () => {
      clearTimeout(timer15s);
      clearTimeout(timer60s);
    };
  }, [connectionState]);

  // Auto-scroll do transcript
  useEffect(() => {
    if (transcriptEndRef.current) {
      transcriptEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [transcript.length]);

  const handleUploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await safeFetch(`/api/projects/${projectId}/documents`, {
        method: "POST",
        body: formData,
      });
      const result = await res.json();
      if (result.success && result.doc) {
         setDocs(prev => [result.doc, ...prev]);
         // Mensagem visual no chat
         addTranscriptMessage("Sistema", `O documento "${file.name}" foi disponibilizado para o Marco.`);
         // Notificar via datachannel se estivermos conectados para o Python Worker atualizar contexto sob demanda (opcional se não quiser enviar o pacote via python)
         if (roomRef.current && connectionState === "connected") {
            const enc = new TextEncoder();
            const packet = JSON.stringify({ type: "DOCUMENT_UPLOADED", fileName: file.name });
            roomRef.current.localParticipant.publishData(enc.encode(packet), { reliable: true });
         }
      }
    } catch (error) {
       console.error("Upload error", error);
       alert("Erro ao enviar arquivo.");
    } finally {
       setIsUploading(false);
       if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const addTranscriptMessage = useCallback((speaker: string, text: string) => {
    setTranscript((prev) => {
      // Evita duplicatas
      const lastMsg = prev[prev.length - 1];
      if (lastMsg && lastMsg.speaker === speaker && lastMsg.text === text) {
        return prev;
      }
      const timestamp = new Date().toLocaleTimeString("pt-BR", {
        hour: "2-digit",
        minute: "2-digit",
      });
      return [...prev, { speaker, text, timestamp }];
    });
  }, []);

  // ─── Conexão LiveKit ────────────────────────────────────────────────────────
  // Esta conexão é inicializada apenas uma vez e persiste enquanto o componente existir.
  // O LiveKit SDK gerencia reconexões automaticamente quando a aba é minimizada.

  useEffect(() => {
    // Só conecta se autenticado e ainda não iniciou
    if (authStatus !== "authenticated" || !session?.user) return;
    if (connectionStartedRef.current) return;
    connectionStartedRef.current = true;

    // Verifica se já existe uma sala conectada (por exemplo, em caso de hot reload)
    if (roomRef.current?.state === ConnectionState.Connected) {
      console.log("[Room] Sala já conectada.");
      return;
    }

    // Guard: evita dupla chamada simultânea (React Strict Mode double-mount)
    if (sessionCreatingRef.current) {
      console.log("[Room] Criação de sessão já em andamento, ignorando.");
      return;
    }
    sessionCreatingRef.current = true;

    // CORREÇÃO P3 / P8: acesso tipado via AuthUser, sem cast (as any)
    const user = session.user as AuthUser;
    const userId = user.id;
    const userName = user.name ?? "Usuário";

    let room: Room | null = null;
    let isMounted = true;

    async function connect() {
      try {
        setConnectionState("connecting");

        // Cria a sessão de mentoria no backend
        const sessionRes = await safeFetch("/api/sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ projectId, userId }),
        });
        if (!isMounted) return;

        const { sessionId: sid, roomName } = await sessionRes.json();
        setSessionId(sid);
        sessionDataRef.current = { sessionId: sid, roomName, userId };

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
        if (!isMounted) return;

        const { token, url } = await tokenRes.json();
        sessionDataRef.current = { ...sessionDataRef.current, token, url };

        // Configura a sala
        room = new Room({
          adaptiveStream: true,
          dynacast: true,
          // IMPORTANTE: não desconecta quando a aba é minimizada
          disconnectOnPageLeave: false,
          // Reconexão automática com delays progressivos
          reconnectPolicy: new DefaultReconnectPolicy(
            [500, 1000, 2000, 5000, 10000, 30000]
          ),
          // Web Audio API para melhor cancelamento de eco e processamento de áudio
          webAudioMix: true,
          audioCaptureDefaults: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1, // Mono — melhor qualidade para captura de voz
          },
          publishDefaults: {
            dtx: true, // Corte de transmissão em silêncio
            red: true, // Codificação redundante contra perda de pacotes
          },
        });

        // ── Eventos da sala ──────────────────────────────────────────────────

        room.on(RoomEvent.Connected, async () => {
          // CORREÇÃO StrictMode: NÃO desconectar quando isMounted=false.
          // Apenas ignora — o cleanup do useEffect cuida da desconexão.
          if (!isMounted) return;
          roomRef.current = room;
          setConnectionState("connected");
          // F5: Host (Nathália) conecta com o room principal — marcar como conectado
          setConnectedAgents((prev) => new Set(prev).add("host"));
          addTranscriptMessage("Sistema", "Conectado! Aguardando os especialistas...");

          // Detecta agentes que já estavam na sala antes do frontend conectar
          for (const [, p] of room!.remoteParticipants) {
            const pid = p.identity;
            if (pid.startsWith("agent-")) {
              const agId = pid.replace("agent-", "");
              if (AGENTS_MAP[agId]) {
                setConnectedAgents((prev) => new Set(prev).add(agId));
              }
            }
          }

          try {
            await room!.localParticipant.setMicrophoneEnabled(true);
          } catch (micErr) {
            console.warn("[LiveKit] Erro ao ativar microfone:", micErr);
          }
        });

        // Desconexão intencional vs. perda de conexão
        room.on(RoomEvent.Disconnected, (reason?: DisconnectReason) => {
          if (reason === DisconnectReason.CLIENT_INITIATED) {
            console.log("[Room] Desconexão intencional.");
            return;
          }
          console.log("[Room] Desconectado pelo servidor, tentando reconectar...");
          setConnectionState("reconnecting");
        });

        // Eventos de reconexão automática
        room.on(RoomEvent.Reconnecting, () => {
          isReconnectingRef.current = true;
          setConnectionState("reconnecting");
        });

        room.on(RoomEvent.Reconnected, () => {
          isReconnectingRef.current = false;
          setConnectionState("connected");
          addTranscriptMessage("Sistema", "Reconectado!");
        });

        // Track de áudio
        room.on(
          RoomEvent.TrackSubscribed,
          (track, _pub, participant: RemoteParticipant) => {
            if (track.kind === Track.Kind.Audio && audioContainerRef.current) {
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
          (payload: Uint8Array) => {
            try {
              const data = JSON.parse(new TextDecoder().decode(payload));

              if (data.type === "transcript") {
                addTranscriptMessage(data.speaker, data.text);
              } else if (data.type === "execution_plan") {
                setExecutionPlan(data.plan ?? data.text ?? "");
                setShowPlan(true);
                addTranscriptMessage(
                  "Marco",
                  "Plano de Execução gerado!"
                );
              } else if (data.type === "session_end") {
                handleSessionCompleted(data.transcript);
              } else if (data.type === "agent_ready") {
                // F5: Marca o agente como conectado quando recebe health-check do backend
                const agentId = data.agent_id as string;
                if (agentId) {
                  setConnectedAgents((prev) => new Set(prev).add(agentId));
                }
              }
            } catch {
              // ignorar
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
                // F5: Fallback — também marca como conectado via ParticipantConnected
                setConnectedAgents((prev) => new Set(prev).add(agentId));
                addTranscriptMessage("Sistema", `${agent.name} entrou.`);
              }
            }
          }
        );

        // Conecta ao room
        await room.connect(url, token);
        console.log("[Room] Conectado com sucesso.");

      } catch (error) {
        if (!isMounted) return;
        console.error("[LiveKit] Erro ao conectar:", error);
        setConnectionState("error");
        addTranscriptMessage("Sistema", "Erro ao conectar.");
        connectionStartedRef.current = false; // Permite tentar novamente
      }
    }

    connect();

    // CORREÇÃO StrictMode: cleanup desconecta a sala e reseta os refs
    // para que o re-mount possa reconectar normalmente.
    return () => {
      isMounted = false;
      sessionCreatingRef.current = false;
      connectionStartedRef.current = false; // Permite re-mount reconectar
      if (room && room.state !== ConnectionState.Disconnected) {
        room.disconnect();
      }
      audioContainerRef.current
        ?.querySelectorAll("audio")
        .forEach((el) => el.remove());
    };
  }, [authStatus, session]); // Re-executa quando auth muda de loading→authenticated

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
        <Loader2 className="w-8 h-8 text-[#d4af37] animate-spin" />
      </div>
    );
  }

  if (authStatus === "unauthenticated") return null;

  const agents = Object.values(AGENTS_MAP).map((a) => ({
    ...a,
    speaking: activeSpeakers.has(a.id),
    connected: connectedAgents.has(a.id),
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
      <div ref={audioContainerRef} style={{ position: 'absolute', width: 0, height: 0, overflow: 'hidden', pointerEvents: 'none' }} aria-hidden="true" />

      {/* Top Bar */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-900/80 backdrop-blur-sm border-b border-white/5 shrink-0">
        <div className="flex items-center gap-3">
          <div className="bg-gradient-to-r from-[#d4af37] to-[#b08d24] p-1 rounded-md">
            <img src="/logo-icon.svg" alt="Hive Mind" className="w-4 h-4" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-white">Sala de Mentoria</h1>
            <p className="text-xs text-gray-400">4 especialistas e a apresentadora • Sessão ao vivo</p>
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

          <button
            onClick={() => setShowUpload(true)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors bg-white/5 text-gray-400 hover:text-white"
            title="Anexos do Negócio"
          >
            <Paperclip className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Anexos</span>
          </button>

          {executionPlan && (
            <button
              onClick={() => setShowPlan((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${showPlan
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
            className={`p-2 rounded-lg transition-colors ${showTranscript
              ? "bg-[#d4af37]/20 text-[#d4af37]"
              : "bg-white/5 text-gray-400 hover:text-white"
              }`}
          >
            <MessageSquare className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* F4: Aviso de conexão lenta */}
      {connectionState === "connecting" && connectingTooLong && (
        <div className="px-4 py-2 bg-amber-900/30 border-b border-amber-500/20 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />
            <span className="text-xs text-amber-300 font-medium">
              {connectingTimedOut
                ? "A conexão está demorando demais. Tente recarregar a página."
                : "Conectando ao servidor... Aguarde um momento."}
            </span>
          </div>
          {connectingTimedOut && (
            <button
              onClick={() => window.location.reload()}
              className="px-3 py-1 rounded-lg bg-amber-500/20 text-amber-300 text-xs font-medium hover:bg-amber-500/30 transition-colors border border-amber-500/30"
            >
              Recarregar
            </button>
          )}
        </div>
      )}

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
              animate={{ width: 420, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              className="bg-gray-900/90 border-l border-violet-500/20 flex flex-col overflow-hidden shrink-0"
            >
              <div className="p-4 border-b border-white/5">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Star className="w-4 h-4 text-violet-400 shrink-0" />
                    <div>
                      <h3 className="text-sm font-semibold text-white">
                        Plano de Execução
                      </h3>
                      <p className="text-xs text-gray-500">
                        por Marco – Estrategista Chefe
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      if (sessionId) {
                        window.open(`/api/execution-plan/${sessionId}`, "_blank");
                      }
                    }}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-violet-500/20 text-violet-300 text-xs font-medium hover:bg-violet-500/30 transition-colors border border-violet-500/30"
                    title="Baixar PDF do Plano"
                  >
                    <FileText className="w-3.5 h-3.5" />
                    PDF
                  </button>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setShowPlan("content")}
                    className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${(showPlan as string) === "content"
                      ? "bg-violet-500/20 text-violet-300 border border-violet-500/30"
                      : "bg-white/5 text-gray-400 hover:text-white border border-transparent"
                      }`}
                  >
                    Conteúdo
                  </button>
                  <button
                    onClick={() => setShowPlan("checklist")}
                    className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${(showPlan as string) === "checklist"
                      ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                      : "bg-white/5 text-gray-400 hover:text-white border border-transparent"
                      }`}
                  >
                    Checklist
                  </button>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-4">
                {(showPlan as string) === "content" ? (
                  <ExecutionPlanRenderer content={executionPlan} />
                ) : (
                  <ChecklistView content={executionPlan} />
                )}
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
          className={`w-12 h-12 rounded-full flex items-center justify-center transition-all ${isMuted
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
                  className="flex-1 px-4 py-2.5 rounded-xl bg-[#b08d24] hover:bg-[#a07e1e] text-white transition-colors text-sm flex items-center justify-center gap-2"
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

      {/* Modal de Upload de Anexos */}
      {showUpload && (
        <div className="fixed inset-0 z-[60] bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <motion.div 
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-gray-950 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl"
          >
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Paperclip className="w-5 h-5 text-emerald-400" />
                Anexos do Negócio
              </h3>
              <button onClick={() => setShowUpload(false)} className="text-gray-400 hover:text-white transition-colors">
                ✕
              </button>
            </div>
            
            <p className="text-sm text-gray-400 mb-6 font-mono leading-relaxed">
              O <span className="text-violet-400 font-semibold">Marco</span> pode analisar PDFs e documentos extraídos com a IA para ajudar os especialistas.
            </p>

            {docs.length > 0 && (
              <div className="mb-6 space-y-2">
                <p className="text-xs font-semibold text-gray-500 uppercase">Arquivos na Base ({docs.length})</p>
                {docs.map(doc => (
                  <div key={doc.id} className="flex items-center gap-2 bg-white/5 py-2 px-3 rounded text-sm text-gray-300">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                    <span className="truncate">{doc.fileName}</span>
                  </div>
                ))}
              </div>
            )}

            <button 
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading}
              className="w-full relative py-6 border-2 border-dashed border-white/20 rounded-xl flex flex-col items-center justify-center gap-3 hover:border-emerald-500/50 hover:bg-emerald-500/5 transition-all text-gray-400 hover:text-emerald-400 disabled:opacity-50"
            >
              {isUploading ? (
                <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
              ) : (
                <UploadCloud className="w-8 h-8" />
              )}
              <span className="text-sm font-medium">{isUploading ? "Processando e validando segurança..." : "Clique para selecionar arquivos"}</span>
              <span className="text-[10px] text-gray-500">Apenas formatos puros (TXT, CSV, PDF simples, MD) (Máx. 50MB)</span>
            </button>
            <input 
              type="file" 
              ref={fileInputRef} 
              className="hidden" 
              onChange={handleUploadFile}
              accept=".pdf,.txt,.csv,.md"
            />
          </motion.div>
        </div>
      )}
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

// ─── ExecutionPlanRenderer ─────────────────────────────────────────────────────

function ExecutionPlanRenderer({ content }: { content: string }) {
  const tokens = tokenize(content);

  return (
    <div className="space-y-1">
      {tokens.map((tok, i) => {
        switch (tok.type) {
          case "h1":
            return (
              <h1 key={i} className="text-white font-bold text-base mt-4 mb-2 first:mt-0 flex items-center gap-2">
                <Star className="w-4 h-4 text-violet-400" />
                {parseInline(tok.text)}
              </h1>
            );
          case "h2":
            return (
              <h2 key={i} className="text-violet-300 font-semibold text-xs mt-4 mb-2 first:mt-0 border-b border-violet-500/20 pb-1">
                {parseInline(tok.text)}
              </h2>
            );
          case "h3":
            return (
              <h3 key={i} className="text-emerald-300 font-medium text-xs mt-3 mb-1 flex items-center gap-1.5">
                <div className="w-1 h-1 rounded-full bg-emerald-400" />
                {parseInline(tok.text)}
              </h3>
            );
          case "hr":
            return <hr key={i} className="border-white/10 my-4" />;
          case "code_block":
            return (
              <pre key={i} className="bg-gray-950 border border-white/10 rounded-lg p-3 overflow-x-auto my-2">
                <code className="text-violet-300 text-[11px] font-mono">{tok.code}</code>
              </pre>
            );
          case "ul":
            return (
              <ul key={i} className="list-disc pl-5 my-1.5 space-y-1">
                {renderListItems(tok.items)}
              </ul>
            );
          case "ol":
            return (
              <ol key={i} className="list-decimal pl-5 my-1.5 space-y-1">
                {renderListItems(tok.items)}
              </ol>
            );
          case "p":
            return <p key={i} className="text-gray-300 text-xs leading-relaxed">{parseInline(tok.text)}</p>;
          case "blank":
            return <div key={i} className="h-2" />;
          default:
            return null;
        }
      })}
    </div>
  );
}

// ─── ChecklistView ────────────────────────────────────────────────────────────

type ChecklistItem = {
  id: string;
  text: string;
  category: string;
  completed: boolean;
};

function ChecklistView({ content }: { content: string }) {
  const [checklist, setChecklist] = useState<ChecklistItem[]>(() => {
    const items: ChecklistItem[] = [];
    const lines = content.split("\n");
    let category = "Ações";

    lines.forEach((line, idx) => {
      const trimmed = line.trim();

      if (trimmed.startsWith("# ")) {
        category = trimmed.substring(2).replace(/\*\*/g, "");
      }

      if (trimmed.includes("[ ]") || trimmed.includes("☐")) {
        const text = trimmed
          .replace(/^[-*\d.]\s*/, "")
          .replace(/[ ]\s*$/, "")
          .replace(/\[ \]/g, "")
          .replace(/☐/g, "")
          .replace(/\*\*/g, "")
          .trim();

        if (text) {
          items.push({
            id: `item-${idx}`,
            text,
            category,
            completed: false,
          });
        }
      }
    });

    return items;
  });

  const [completedCount, setCompletedCount] = useState(0);

  const toggleItem = (id: string) => {
    setChecklist((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, completed: !item.completed } : item
      )
    );
  };

  useEffect(() => {
    setCompletedCount(checklist.filter((item) => item.completed).length);
  }, [checklist]);

  const progress = checklist.length > 0 ? (completedCount / checklist.length) * 100 : 0;

  const groupedItems = checklist.reduce((acc, item) => {
    if (!acc[item.category]) {
      acc[item.category] = [];
    }
    acc[item.category].push(item);
    return acc;
  }, {} as Record<string, ChecklistItem[]>);

  return (
    <div className="space-y-4">
      {/* Progress bar */}
      <div className="bg-gray-800/50 rounded-xl p-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-gray-400 font-medium">Progresso</span>
          <span className="text-xs text-emerald-400 font-bold">
            {completedCount}/{checklist.length}
          </span>
        </div>
        <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-emerald-500 to-teal-400"
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
      </div>

      {/* Checklist items */}
      {Object.entries(groupedItems).map(([category, items]) => (
        <div key={category}>
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
            {category}
          </h4>
          <div className="space-y-1.5">
            {items.map((item) => (
              <button
                key={item.id}
                onClick={() => toggleItem(item.id)}
                className={`w-full text-left flex items-start gap-2.5 p-2.5 rounded-lg transition-all ${item.completed
                  ? "bg-emerald-500/10 border border-emerald-500/20"
                  : "bg-white/5 border border-white/10 hover:border-white/20"
                  }`}
              >
                <div
                  className={`w-4 h-4 rounded border-2 flex items-center justify-center shrink-0 mt-0.5 transition-all ${item.completed
                    ? "bg-emerald-500 border-emerald-500"
                    : "border-gray-500"
                    }`}
                >
                  {item.completed && (
                    <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </div>
                <span
                  className={`text-xs leading-relaxed transition-all ${item.completed ? "text-gray-500 line-through" : "text-gray-300"
                    }`}
                >
                  {item.text}
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}

      {checklist.length === 0 && (
        <div className="text-center py-8">
          <p className="text-gray-500 text-xs">
            Nenhuma ação encontrada no plano.
          </p>
          <p className="text-gray-600 text-[10px] mt-1">
            Solicite a Marco para gerar o checklist de ações.
          </p>
        </div>
      )}
    </div>
  );
}

// ─── AgentCard ────────────────────────────────────────────────────────────────

function AgentCard({
  agent,
  compact = false,
}: {
  agent: AgentInfo & { connected?: boolean };
  compact?: boolean;
}) {
  const Icon = agent.icon;

  return (
    <motion.div
      layout
      className={`relative rounded-2xl overflow-hidden border-2 transition-all duration-500 ${compact ? "h-40" : "h-full"
        } ${agent.speaking
          ? "border-[#d4af37]/70 shadow-lg shadow-[#d4af37]/20"
          : agent.connected
            ? "border-emerald-500/30 hover:border-emerald-500/50"
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
              : { scale: 1, opacity: agent.connected ? 0.6 : 0.35 }
          }
          transition={
            agent.speaking
              ? { duration: 1.2, repeat: Infinity, ease: "easeInOut" }
              : {}
          }
          className={`${compact ? "w-14 h-14" : "w-20 h-20 sm:w-24 sm:h-24"
            } rounded-full bg-gradient-to-r ${agent.gradient} flex items-center justify-center`}
        >
          <Icon
            className={`${compact ? "w-7 h-7" : "w-10 h-10 sm:w-12 sm:h-12"
              } text-white`}
          />
        </motion.div>
      </div>

      {/* F5: Status badge — Conectado ou Aguardando */}
      {!agent.speaking && (
        <div className="absolute top-3 right-3">
          {agent.connected ? (
            <div className="flex items-center gap-1 bg-emerald-500/20 border border-emerald-500/30 rounded-full px-2 py-1">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              <span className="text-[10px] text-emerald-300 font-medium">
                Conectado
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-1 bg-white/5 border border-white/10 rounded-full px-2 py-1">
              <Loader2 className="w-2.5 h-2.5 text-gray-400 animate-spin" />
              <span className="text-[10px] text-gray-400 font-medium">
                Aguardando...
              </span>
            </div>
          )}
        </div>
      )}

      {/* Speaking indicator */}
      {agent.speaking && (
        <div className="absolute top-3 right-3">
          <div className="flex items-center gap-1.5 bg-[#d4af37]/20 border border-[#d4af37]/30 rounded-full px-2 py-1">
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
                  className="w-[3px] bg-[#d4af37] rounded-full"
                />
              ))}
            </div>
            <span className="text-[10px] text-[#e6c86a] font-medium">
              Falando
            </span>
          </div>
        </div>
      )}

      {/* Name badge */}
      <div className="absolute bottom-0 left-0 right-0 p-3 bg-gradient-to-t from-black/80 to-transparent">
        <p
          className={`font-semibold text-white ${compact ? "text-xs" : "text-sm"
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