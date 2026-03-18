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
  Volume2,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import {
  Room,
  RoomEvent,
  Track,
  Participant,
  RemoteParticipant,
  RemoteTrackPublication,
  LocalParticipant,
  ConnectionState,
  DataPacket_Kind,
} from "livekit-client";

// ============================================================
// TIPOS E DADOS DOS AGENTES
// ============================================================

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
    role: "CFO - Financeiro",
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
    role: "CMO - Marketing",
    icon: Users,
    gradient: "from-pink-500 to-rose-600",
  },
  cto: {
    id: "cto",
    name: "Ana",
    role: "CTO - Tecnologia",
    icon: Code,
    gradient: "from-blue-500 to-cyan-600",
  },
};

type TranscriptMessage = {
  speaker: string;
  text: string;
  timestamp: string;
};

// ============================================================
// PÁGINA PRINCIPAL
// ============================================================

export default function MentorshipRoomPage() {
  const params = useParams();
  const router = useRouter();
  const { data: session, status: authStatus } = useSession();
  const projectId = params.projectId as string;

  // Estados
  const [connectionState, setConnectionState] = useState<"connecting" | "connected" | "error">("connecting");
  const [isMuted, setIsMuted] = useState(false);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [showEndConfirm, setShowEndConfirm] = useState(false);
  const [ending, setEnding] = useState(false);
  const [activeSpeakers, setActiveSpeakers] = useState<Set<string>>(new Set());
  const [transcript, setTranscript] = useState<TranscriptMessage[]>([]);
  const [showTranscript, setShowTranscript] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Refs
  const roomRef = useRef<Room | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  // Auth check
  useEffect(() => {
    if (authStatus === "unauthenticated") {
      router.replace("/login");
    }
  }, [authStatus, router]);

  // Timer
  useEffect(() => {
    timerRef.current = setInterval(() => {
      setElapsedTime((t) => t + 1);
    }, 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  // Auto-scroll transcrição
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  // ============================================================
  // CONEXÃO LIVEKIT
  // ============================================================

  const connectToRoom = useCallback(async () => {
    if (!session?.user || !projectId) return;

    try {
      const userId = (session.user as any).id;
      const userName = session.user.name || "Usuário";

      // 1. Criar sessão de mentoria no banco
      const sessionRes = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId, userId }),
      });

      if (!sessionRes.ok) throw new Error("Falha ao criar sessão");
      const { sessionId: sid, roomName } = await sessionRes.json();
      setSessionId(sid);

      // 2. Obter token LiveKit
      const tokenRes = await fetch("/api/livekit/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          roomName,
          participantName: userName,
          participantIdentity: `user-${userId}`,
        }),
      });

      if (!tokenRes.ok) throw new Error("Falha ao obter token");
      const { token, url } = await tokenRes.json();

      // 3. Criar e conectar ao Room
      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
      });

      roomRef.current = room;

      // Event listeners
      room.on(RoomEvent.Connected, () => {
        setConnectionState("connected");
        addTranscriptMessage("Sistema", "Conectado à sala de mentoria. Aguardando os especialistas...");
      });

      room.on(RoomEvent.Disconnected, () => {
        setConnectionState("error");
      });

      // Quando agente publica áudio, inscrevemos automaticamente
      room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
        if (track.kind === Track.Kind.Audio) {
          const el = track.attach();
          el.id = `audio-${participant.identity}`;
          document.body.appendChild(el);
        }
      });

      room.on(RoomEvent.TrackUnsubscribed, (track, publication, participant) => {
        const el = document.getElementById(`audio-${participant.identity}`);
        if (el) el.remove();
        track.detach();
      });

      // Detectar quem está falando
      room.on(RoomEvent.ActiveSpeakersChanged, (speakers: Participant[]) => {
        const speakerIds = new Set(speakers.map((s) => {
          const identity = s.identity;
          // Mapear identidade do agente para o ID do especialista
          if (identity.startsWith("agent-")) {
            return identity.replace("agent-", "");
          }
          return "user";
        }));
        setActiveSpeakers(speakerIds);
      });

      // Receber mensagens de dados (transcrição) dos agentes
      room.on(RoomEvent.DataReceived, (payload: Uint8Array, participant?: RemoteParticipant) => {
        try {
          const decoder = new TextDecoder();
          const data = JSON.parse(decoder.decode(payload));

          if (data.type === "transcript") {
            addTranscriptMessage(data.speaker, data.text);
          } else if (data.type === "session_end") {
            // Agentes finalizaram → redirecionar
            handleSessionCompleted(data.transcript);
          }
        } catch (err) {
          // Ignorar mensagens mal formatadas
        }
      });

      // Participante conectou
      room.on(RoomEvent.ParticipantConnected, (participant: RemoteParticipant) => {
        const identity = participant.identity;
        if (identity.startsWith("agent-")) {
          const agentId = identity.replace("agent-", "");
          const agent = AGENTS_MAP[agentId];
          if (agent) {
            addTranscriptMessage("Sistema", `${agent.name} (${agent.role}) entrou na sala.`);
          }
        }
      });

      // Conectar
      await room.connect(url, token);

      // Publicar microfone do usuário
      await room.localParticipant.setMicrophoneEnabled(true);

    } catch (error) {
      console.error("Erro ao conectar:", error);
      setConnectionState("error");
      addTranscriptMessage("Sistema", "Erro ao conectar à sala. Verifique sua conexão.");
    }
  }, [session, projectId]);

  useEffect(() => {
    if (authStatus === "authenticated" && session?.user) {
      connectToRoom();
    }

    return () => {
      // Limpar ao desmontar
      if (roomRef.current) {
        roomRef.current.disconnect();
        roomRef.current = null;
      }
    };
  }, [authStatus, connectToRoom]);

  // ============================================================
  // HANDLERS
  // ============================================================

  const addTranscriptMessage = (speaker: string, text: string) => {
    const now = new Date();
    const timestamp = now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    setTranscript((prev) => [...prev, { speaker, text, timestamp }]);
  };

  const toggleMute = async () => {
    if (roomRef.current?.localParticipant) {
      await roomRef.current.localParticipant.setMicrophoneEnabled(isMuted);
      setIsMuted(!isMuted);
    }
  };

  const handleEndSession = async () => {
    setEnding(true);
    try {
      // Enviar mensagem para os agentes encerrarem apenas se estiver conectado
      if (roomRef.current && roomRef.current.state === ConnectionState.Connected) {
        try {
          const encoder = new TextEncoder();
          const data = encoder.encode(JSON.stringify({ type: "end_session" }));
          await roomRef.current.localParticipant.publishData(data, { reliable: true });
          
          // Aguardar um momento para os agentes processarem
          await new Promise((resolve) => setTimeout(resolve, 1000));
        } catch (pubErr) {
          console.warn("Não foi possível enviar mensagem de encerramento:", pubErr);
        }
      }

      // Finalizar sessão via API
      if (sessionId) {
        const fullTranscript = transcript.map((m) => `[${m.speaker}]: ${m.text}`).join("\n");
        await fetch("/api/sessions/finalize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sessionId,
            transcript: fullTranscript,
          }),
        });
      }

      // Desconectar e voltar ao dashboard
      if (roomRef.current) {
        await roomRef.current.disconnect();
      }
      router.push("/dashboard");
    } catch (err) {
      console.error("Erro ao encerrar:", err);
      setEnding(false);
      // Fallback em caso de erro crítico: redirecionar mesmo assim para o dashboard
      router.push("/dashboard");
    }
  };

  const handleSessionCompleted = async (fullTranscript?: string) => {
    if (sessionId) {
      await fetch("/api/sessions/finalize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId,
          transcript: fullTranscript || transcript.map((m) => `[${m.speaker}]: ${m.text}`).join("\n"),
        }),
      });
    }
    roomRef.current?.disconnect();
    router.push("/dashboard");
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, "0");
    const s = (seconds % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  };

  // ============================================================
  // LOADING STATES
  // ============================================================

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

  // ============================================================
  // RENDER
  // ============================================================

  return (
    <div className="h-screen flex flex-col bg-gray-950">
      {/* Top Bar */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-900/80 backdrop-blur-sm border-b border-white/5">
        <div className="flex items-center gap-3">
          <div className="bg-gradient-to-r from-indigo-500 to-purple-600 p-1.5 rounded-lg">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-white">Sala de Mentoria</h1>
            <p className="text-xs text-gray-400">Sessão em andamento</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {/* Connection status */}
          <div className="flex items-center gap-2">
            {connectionState === "connected" ? (
              <Wifi className="w-3.5 h-3.5 text-emerald-400" />
            ) : connectionState === "connecting" ? (
              <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />
            ) : (
              <WifiOff className="w-3.5 h-3.5 text-red-400" />
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            <span className="text-sm text-gray-400 font-mono">{formatTime(elapsedTime)}</span>
          </div>
          <button
            onClick={() => setShowTranscript(!showTranscript)}
            className={`p-2 rounded-lg transition-colors ${
              showTranscript
                ? "bg-indigo-500/20 text-indigo-400"
                : "bg-white/5 text-gray-400 hover:text-white"
            }`}
            title="Transcrição"
          >
            <MessageSquare className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Agents Grid */}
        <div className={`flex-1 p-3 sm:p-4 transition-all ${showTranscript ? "lg:mr-0" : ""}`}>
          {/* Desktop: 5 columns */}
          <div className="hidden md:grid grid-cols-5 gap-3 h-full">
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>

          {/* Mobile: Host + 2x2 grid */}
          <div className="md:hidden flex flex-col gap-3 h-full">
            <div className="flex-1">
              <AgentCard agent={agents[0]} />
            </div>
            <div className="grid grid-cols-2 gap-3 h-1/2">
              {agents.slice(1).map((agent) => (
                <AgentCard key={agent.id} agent={agent} />
              ))}
            </div>
          </div>
        </div>

        {/* Transcript Panel */}
        <AnimatePresence>
          {showTranscript && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: 360, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              className="bg-gray-900/80 border-l border-white/5 flex flex-col overflow-hidden"
            >
              <div className="p-4 border-b border-white/5">
                <h3 className="text-sm font-semibold text-white">Transcrição</h3>
                <p className="text-xs text-gray-500">{transcript.length} mensagens</p>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {transcript.map((msg, i) => (
                  <div key={i} className="text-sm">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`font-semibold ${
                        msg.speaker === "Sistema" ? "text-gray-500" : "text-indigo-400"
                      }`}>
                        {msg.speaker}
                      </span>
                      <span className="text-[10px] text-gray-600">{msg.timestamp}</span>
                    </div>
                    <p className="text-gray-300 leading-relaxed">{msg.text}</p>
                  </div>
                ))}
                <div ref={transcriptEndRef} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Controls Bar */}
      <div className="flex items-center justify-center gap-4 px-4 py-4 bg-gray-900/80 backdrop-blur-sm border-t border-white/5">
        <motion.button
          whileTap={{ scale: 0.9 }}
          onClick={toggleMute}
          className={`w-12 h-12 rounded-full flex items-center justify-center transition-all ${
            isMuted
              ? "bg-red-500/20 border border-red-500/50 text-red-400"
              : "bg-white/10 border border-white/10 text-white hover:bg-white/20"
          }`}
          title={isMuted ? "Ativar microfone" : "Desativar microfone"}
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
              className="glass-card p-8 max-w-md w-full text-center"
            >
              <div className="w-16 h-16 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center mx-auto mb-4">
                <PhoneOff className="w-8 h-8 text-red-400" />
              </div>
              <h2 className="text-xl font-bold text-white mb-2">Encerrar Mentoria?</h2>
              <p className="text-sm text-gray-400 mb-6">
                Ao encerrar, o Plano de Execução será gerado automaticamente e ficará disponível no seu Dashboard.
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => setShowEndConfirm(false)}
                  className="btn-secondary flex-1"
                  disabled={ending}
                >
                  Continuar
                </button>
                <button
                  onClick={handleEndSession}
                  disabled={ending}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
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

// ============================================================
// COMPONENTE AGENT CARD
// ============================================================

function AgentCard({ agent }: { agent: AgentInfo }) {
  const Icon = agent.icon;

  return (
    <motion.div
      layout
      className={`relative rounded-2xl overflow-hidden h-full border-2 transition-all duration-500 ${
        agent.speaking
          ? "border-indigo-500/70 shadow-lg shadow-indigo-500/20"
          : "border-white/5 hover:border-white/10"
      }`}
    >
      {/* Background gradient */}
      <div className={`absolute inset-0 bg-gradient-to-br ${agent.gradient} opacity-10`} />
      <div className="absolute inset-0 bg-gray-900/70" />

      {/* Avatar */}
      <div className="absolute inset-0 flex items-center justify-center">
        <motion.div
          animate={
            agent.speaking
              ? { scale: [1, 1.08, 1], opacity: [0.5, 0.9, 0.5] }
              : { scale: 1, opacity: 0.3 }
          }
          transition={
            agent.speaking
              ? { duration: 1, repeat: Infinity, ease: "easeInOut" }
              : {}
          }
          className={`w-20 h-20 sm:w-24 sm:h-24 rounded-full bg-gradient-to-r ${agent.gradient} flex items-center justify-center`}
        >
          <Icon className="w-10 h-10 sm:w-12 sm:h-12 text-white" />
        </motion.div>
      </div>

      {/* Speaking Indicator */}
      {agent.speaking && (
        <div className="absolute top-3 right-3">
          <div className="flex items-center gap-1.5 bg-indigo-500/20 border border-indigo-500/30 rounded-full px-2.5 py-1">
            <div className="flex items-center gap-0.5">
              {[...Array(3)].map((_, i) => (
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
            <span className="text-[10px] text-indigo-300 font-medium">Falando</span>
          </div>
        </div>
      )}

      {/* Name Badge */}
      <div className="absolute bottom-0 left-0 right-0 p-3 bg-gradient-to-t from-black/80 to-transparent">
        <p className="text-sm font-semibold text-white">{agent.name}</p>
        <p className="text-xs text-gray-300">{agent.role}</p>
      </div>
    </motion.div>
  );
}
