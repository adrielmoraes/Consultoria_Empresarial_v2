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
  ChevronDown,
  ChevronUp,
  Star,
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
  ConnectionState,
} from "livekit-client";

// ============================================================
// TIPOS E DADOS DOS AGENTES (6 agentes)
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

  const [connectionState, setConnectionState] = useState<"connecting" | "connected" | "error">("connecting");
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
  const connectingRef = useRef(false);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (authStatus === "unauthenticated") router.replace("/login");
  }, [authStatus, router]);

  useEffect(() => {
    timerRef.current = setInterval(() => setElapsedTime((t) => t + 1), 1000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  const addTranscriptMessage = useCallback((speaker: string, text: string) => {
    const timestamp = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    setTranscript((prev) => [...prev, { speaker, text, timestamp }]);
  }, []);

  // ============================================================
  // CONEXÃO LIVEKIT
  // ============================================================

  const connectToRoom = useCallback(async () => {
    if (!session?.user || !projectId) return;
    if (connectingRef.current || roomRef.current) return;
    connectingRef.current = true;

    try {
      const userId = (session.user as any).id;
      const userName = session.user.name || "Usuário";

      const sessionRes = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectId, userId }),
      });
      if (!sessionRes.ok) throw new Error("Falha ao criar sessão");
      const { sessionId: sid, roomName } = await sessionRes.json();
      setSessionId(sid);

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

      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
        audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      roomRef.current = room;

      room.on(RoomEvent.Connected, async () => {
        setConnectionState("connected");
        addTranscriptMessage("Sistema", "Conectado. Aguardando os especialistas...");
        try {
          await room.localParticipant.setMicrophoneEnabled(true);
        } catch (micErr) {
          console.warn("Erro ao ativar microfone:", micErr);
        }
      });

      room.on(RoomEvent.Disconnected, () => {
        connectingRef.current = false;
        setConnectionState("error");
      });

      room.on(RoomEvent.TrackSubscribed, (track, _pub, participant) => {
        if (track.kind === Track.Kind.Audio) {
          const existing = document.getElementById(`audio-${participant.identity}`);
          if (existing) existing.remove();
          const el = track.attach() as HTMLAudioElement;
          el.id = `audio-${participant.identity}`;
          el.autoplay = true;
          document.body.appendChild(el);
        }
      });

      room.on(RoomEvent.TrackUnsubscribed, (track, _pub, participant) => {
        document.getElementById(`audio-${participant.identity}`)?.remove();
        track.detach();
      });

      room.on(RoomEvent.ActiveSpeakersChanged, (speakers: Participant[]) => {
        const ids = new Set(
          speakers.map((s) => {
            const id = s.identity;
            if (id.startsWith("agent-")) return id.replace("agent-", "");
            if (id === "agent-host" || id.startsWith("user-")) return id.startsWith("user-") ? "user" : "host";
            return id;
          })
        );
        setActiveSpeakers(ids);
      });

      room.on(RoomEvent.DataReceived, (payload: Uint8Array, participant?: RemoteParticipant) => {
        try {
          const data = JSON.parse(new TextDecoder().decode(payload));

          if (data.type === "transcript") {
            addTranscriptMessage(data.speaker, data.text);
          } else if (data.type === "execution_plan") {
            setExecutionPlan(data.plan || data.text || "");
            setShowPlan(true);
            addTranscriptMessage("Marco (Estrategista)", "Plano de Execução gerado com sucesso! Veja o painel lateral.");
          } else if (data.type === "session_end") {
            handleSessionCompleted(data.transcript);
          }
        } catch { /* ignore */ }
      });

      room.on(RoomEvent.ParticipantConnected, (participant: RemoteParticipant) => {
        const id = participant.identity;
        if (id.startsWith("agent-")) {
          const agentId = id.replace("agent-", "");
          const agent = AGENTS_MAP[agentId];
          if (agent) addTranscriptMessage("Sistema", `${agent.name} (${agent.role}) entrou na sessão.`);
        }
      });

      await room.connect(url, token);
    } catch (error) {
      console.error("Erro ao conectar:", error);
      connectingRef.current = false;
      setConnectionState("error");
      addTranscriptMessage("Sistema", "Erro ao conectar. Verifique sua conexão e recarregue.");
    }
  }, [session, projectId, addTranscriptMessage]);

  useEffect(() => {
    if (authStatus === "authenticated" && session?.user) connectToRoom();
    return () => { roomRef.current?.disconnect(); roomRef.current = null; };
  }, [authStatus, connectToRoom]);

  // ============================================================
  // HANDLERS
  // ============================================================

  const toggleMute = async () => {
    if (roomRef.current?.localParticipant) {
      await roomRef.current.localParticipant.setMicrophoneEnabled(isMuted);
      setIsMuted(!isMuted);
    }
  };

  const handleEndSession = async () => {
    setEnding(true);
    try {
      if (roomRef.current && roomRef.current.state === ConnectionState.Connected) {
        try {
          const data = new TextEncoder().encode(JSON.stringify({ type: "end_session" }));
          await roomRef.current.localParticipant.publishData(data, { reliable: true });
          await new Promise((r) => setTimeout(r, 1000));
        } catch { /* best effort */ }
      }

      if (sessionId) {
        const fullTranscript = transcript.map((m) => `[${m.speaker}]: ${m.text}`).join("\n");
        await fetch("/api/sessions/finalize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sessionId,
            transcript: fullTranscript,
            markdownContent: executionPlan || null,
          }),
        });
      }

      await roomRef.current?.disconnect();
      router.push("/dashboard");
    } catch {
      setEnding(false);
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
          markdownContent: executionPlan || null,
        }),
      });
    }
    roomRef.current?.disconnect();
    router.push("/dashboard");
  };

  const formatTime = (s: number) =>
    `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;

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

  const speakerColorMap: Record<string, string> = {
    "Você": "text-white",
    "Sistema": "text-gray-500",
    "Nathália": "text-indigo-400",
    "Carlos (CFO)": "text-emerald-400",
    "Daniel (Advogado)": "text-amber-400",
    "Rodrigo (CMO)": "text-pink-400",
    "Ana (CTO)": "text-blue-400",
    "Marco (Estrategista)": "text-violet-400",
  };
  const getSpeakerColor = (speaker: string) => {
    for (const [key, color] of Object.entries(speakerColorMap)) {
      if (speaker.includes(key.split(" ")[0])) return color;
    }
    return "text-indigo-400";
  };

  // ============================================================
  // RENDER
  // ============================================================

  return (
    <div className="h-screen flex flex-col bg-gray-950">
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
          {connectionState === "connected" ? (
            <Wifi className="w-3.5 h-3.5 text-emerald-400" />
          ) : connectionState === "connecting" ? (
            <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />
          ) : (
            <WifiOff className="w-3.5 h-3.5 text-red-400" />
          )}

          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            <span className="text-sm text-gray-400 font-mono">{formatTime(elapsedTime)}</span>
          </div>

          {executionPlan && (
            <button
              onClick={() => setShowPlan(!showPlan)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                showPlan ? "bg-violet-500/20 text-violet-300 border border-violet-500/30" : "bg-white/5 text-gray-400 hover:text-white"
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              Plano
            </button>
          )}

          <button
            onClick={() => setShowTranscript(!showTranscript)}
            className={`p-2 rounded-lg transition-colors ${
              showTranscript ? "bg-indigo-500/20 text-indigo-400" : "bg-white/5 text-gray-400 hover:text-white"
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
          {/* Desktop: 3 + 3 layout */}
          <div className="hidden md:grid grid-cols-3 grid-rows-2 gap-3 h-full">
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>

          {/* Mobile: vertical scroll */}
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
              <div className="p-4 border-b border-white/5 flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <Star className="w-4 h-4 text-violet-400" />
                    Plano de Execução
                  </h3>
                  <p className="text-xs text-gray-500 mt-0.5">por Marco – Estrategista Chefe</p>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-4">
                <div className="prose prose-sm prose-invert max-w-none">
                  {executionPlan.split("\n").map((line, i) => {
                    if (line.startsWith("## ")) return <h2 key={i} className="text-violet-300 font-bold text-sm mt-4 mb-2">{line.slice(3)}</h2>;
                    if (line.startsWith("# ")) return <h1 key={i} className="text-white font-bold text-base mt-4 mb-2">{line.slice(2)}</h1>;
                    if (line.startsWith("**") && line.endsWith("**")) return <p key={i} className="text-white font-semibold text-xs my-1">{line.slice(2, -2)}</p>;
                    if (line.startsWith("- ") || line.startsWith("* ")) return <p key={i} className="text-gray-300 text-xs my-0.5 pl-3">• {line.slice(2)}</p>;
                    if (/^\d+\./.test(line)) return <p key={i} className="text-gray-300 text-xs my-0.5">{line}</p>;
                    if (!line.trim()) return <div key={i} className="my-2" />;
                    return <p key={i} className="text-gray-400 text-xs my-1">{line}</p>;
                  })}
                </div>
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
                      <span className={`text-xs font-semibold ${getSpeakerColor(msg.speaker)}`}>
                        {msg.speaker}
                      </span>
                      <span className="text-[10px] text-gray-600">{msg.timestamp}</span>
                    </div>
                    <p className="text-gray-300 text-xs leading-relaxed">{msg.text}</p>
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
              <h2 className="text-xl font-bold text-white mb-2">Encerrar Mentoria?</h2>
              <p className="text-sm text-gray-400 mb-6">
                Ao encerrar, o Plano de Execução completo será gerado pelo Marco e salvo no seu Dashboard.
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
                  {ending ? <><Loader2 className="w-4 h-4 animate-spin" />Encerrando...</> : "Encerrar"}
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
// AGENT CARD
// ============================================================

function AgentCard({ agent, compact = false }: { agent: AgentInfo; compact?: boolean }) {
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
      <div className={`absolute inset-0 bg-gradient-to-br ${agent.gradient} opacity-10`} />
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
          className={`${compact ? "w-14 h-14" : "w-20 h-20 sm:w-24 sm:h-24"} rounded-full bg-gradient-to-r ${agent.gradient} flex items-center justify-center`}
        >
          <Icon className={`${compact ? "w-7 h-7" : "w-10 h-10 sm:w-12 sm:h-12"} text-white`} />
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
                  transition={{ duration: 0.5, repeat: Infinity, delay: i * 0.12 }}
                  className="w-[3px] bg-indigo-400 rounded-full"
                />
              ))}
            </div>
            <span className="text-[10px] text-indigo-300 font-medium">Falando</span>
          </div>
        </div>
      )}

      {/* Name badge */}
      <div className="absolute bottom-0 left-0 right-0 p-3 bg-gradient-to-t from-black/80 to-transparent">
        <p className={`font-semibold text-white ${compact ? "text-xs" : "text-sm"}`}>{agent.name}</p>
        <p className={`text-gray-300 ${compact ? "text-[10px]" : "text-xs"}`}>{agent.role}</p>
      </div>
    </motion.div>
  );
}
