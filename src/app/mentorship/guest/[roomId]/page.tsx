"use client";

import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Mic,
  MicOff,
  LogOut,
  TrendingUp,
  Gavel,
  Users,
  Code,
  Loader2,
  MessageSquare,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useState, useEffect, useRef, useCallback } from "react";
import Image from "next/image";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  Room,
  RoomEvent,
  Track,
  Participant,
  RemoteParticipant,
  ConnectionState,
  DefaultReconnectPolicy,
} from "livekit-client";
import {
  buildAudioCaptureOptions,
  inspectAudioInputState,
  resolveMicrophoneError,
} from "@/lib/audio/vad-monitor";
import {
  createNativeAudioCapture,
  type NativeAudioCapture,
} from "@/lib/audio/native-capture";

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

const DATA_PACKET_SCHEMA_VERSION = "1.0";

// ─── Página Guest ─────────────────────────────────────────────────────────────

export default function GuestMentorshipPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const roomId = params.roomId as string;
  const guestName = searchParams.get("name") || "Convidado";
  const roomName = searchParams.get("room") || `mentoria-${roomId}`;

  const [connectionState, setConnectionState] = useState<
    "connecting" | "connected" | "reconnecting" | "error" | "disconnected"
  >("connecting");
  const [isMuted, setIsMuted] = useState(false);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [activeSpeakers, setActiveSpeakers] = useState<Set<string>>(new Set());
  const [transcript, setTranscript] = useState<TranscriptMessage[]>([]);
  const [showTranscript, setShowTranscript] = useState(false);
  const [connectedAgents, setConnectedAgents] = useState<Set<string>>(
    new Set()
  );
  const [micActive, setMicActive] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [micError, setMicError] = useState<string | null>(null);

  const roomRef = useRef<Room | null>(null);
  const audioContainerRef = useRef<HTMLDivElement>(null);
  const nativeCaptureRef = useRef<NativeAudioCapture | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const connectionStartedRef = useRef(false);

  const addTranscriptMessage = useCallback(
    (speaker: string, text: string) => {
      setTranscript((prev) => {
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
    },
    []
  );

  // Timer
  useEffect(() => {
    const id = setInterval(() => setElapsedTime((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // Auto-scroll
  useEffect(() => {
    if (transcriptEndRef.current) {
      transcriptEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [transcript.length]);

  const cleanupAudioPipeline = useCallback((room?: Room | null) => {
    const capture = nativeCaptureRef.current;
    nativeCaptureRef.current = null;
    if (capture) {
      if (room && room.state === ConnectionState.Connected) {
        void room.localParticipant
          .unpublishTrack(capture.localTrack, false)
          .catch(() => undefined);
      }
      capture.cleanup();
    }
    setMicLevel(0);
    setMicActive(false);
  }, []);

  const initializeMicrophone = useCallback(
    async (room: Room) => {
      cleanupAudioPipeline(room);
      try {
        if (room.state !== ConnectionState.Connected) {
          throw new Error("Sala ainda não conectada.");
        }
        await new Promise((resolve) => setTimeout(resolve, 250));
        const probe = await inspectAudioInputState(null);

        const capture = await createNativeAudioCapture({
          deviceId: probe.selectedDeviceId,
          onLog: () => {},
          onDiagnostics: (snapshot) => {
            setMicLevel(snapshot.micLevel);
          },
        });

        nativeCaptureRef.current = capture;

        await room.localParticipant.publishTrack(capture.localTrack, {
          source: Track.Source.Microphone,
          dtx: false,
          red: false,
          forceStereo: false,
          stopMicTrackOnMute: false,
        });

        setMicActive(true);
        setIsMuted(false);
        setMicError(null);
      } catch (err) {
        const message = resolveMicrophoneError(err);
        setMicError(message);
        setMicActive(false);
      }
    },
    [cleanupAudioPipeline]
  );

  // Conexão LiveKit como Guest
  useEffect(() => {
    if (connectionStartedRef.current) return;
    connectionStartedRef.current = true;

    let room: Room | null = null;
    let isMounted = true;

    async function connect() {
      try {
        setConnectionState("connecting");

        // Obter guest token
        const tokenRes = await fetch("/api/livekit/guest-token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ roomName, guestName }),
        });

        if (!tokenRes.ok) {
          throw new Error("Falha ao obter token de acesso");
        }

        const { token, url } = await tokenRes.json();

        room = new Room({
          adaptiveStream: true,
          dynacast: true,
          disconnectOnPageLeave: false,
          reconnectPolicy: new DefaultReconnectPolicy([
            500, 1000, 2000, 5000, 10000,
          ]),
          audioCaptureDefaults: buildAudioCaptureOptions(),
          publishDefaults: {
            dtx: true,
            red: true,
            audioPreset: { maxBitrate: 32000 },
          },
        });

        // Eventos da sala
        room.on(RoomEvent.Connected, async () => {
          if (!isMounted) return;
          roomRef.current = room;
          setConnectionState("connected");
          addTranscriptMessage(
            "Sistema",
            `Conectado como convidado: ${guestName}`
          );

          try {
            await room!.startAudio();
          } catch {}

          // Identifica agentes já na sala
          for (const [, p] of room!.remoteParticipants) {
            const pid = p.identity;
            if (pid.startsWith("agent-")) {
              const agId = pid.replace("agent-", "");
              if (AGENTS_MAP[agId]) {
                setConnectedAgents((prev) => new Set(prev).add(agId));
              }
            }
          }

          // Inicializa microfone
          try {
            await initializeMicrophone(room!);
          } catch {
            setMicError("Erro ao ativar microfone.");
          }
        });

        room.on(RoomEvent.Disconnected, () => {
          if (!isMounted) return;
          setConnectionState("disconnected");
          addTranscriptMessage(
            "Sistema",
            "A sessão foi encerrada pelo anfitrião."
          );
        });

        room.on(RoomEvent.Reconnecting, () =>
          setConnectionState("reconnecting")
        );
        room.on(RoomEvent.Reconnected, () => {
          setConnectionState("connected");
          addTranscriptMessage("Sistema", "Reconectado!");
        });

        // Track de áudio
        room.on(
          RoomEvent.TrackSubscribed,
          (track, _pub, participant: RemoteParticipant) => {
            if (
              track.kind === Track.Kind.Audio &&
              audioContainerRef.current
            ) {
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
                if (id.startsWith("guest-")) return "guest";
                return id;
              })
            );
            setActiveSpeakers(ids);
          }
        );

        room.on(
          RoomEvent.ParticipantConnected,
          (participant: RemoteParticipant) => {
            const id = participant.identity;
            if (id.startsWith("agent-")) {
              const agentId = id.replace("agent-", "");
              if (AGENTS_MAP[agentId]) {
                setConnectedAgents((prev) => new Set(prev).add(agentId));
              }
            }
          }
        );

        room.on(RoomEvent.DataReceived, (payload: Uint8Array) => {
          try {
            const data = JSON.parse(new TextDecoder().decode(payload));
            if (data.type === "transcript") {
              addTranscriptMessage(data.speaker, data.text);
            } else if (data.type === "agent_ready") {
              const agentId = data.agent_id as string;
              if (agentId) {
                setConnectedAgents((prev) => new Set(prev).add(agentId));
              }
            } else if (data.type === "session_end") {
              setConnectionState("disconnected");
              addTranscriptMessage(
                "Sistema",
                "A sessão foi encerrada pelo anfitrião."
              );
              setTimeout(() => room?.disconnect(), 2000);
            }
          } catch {}
        });

        await room.connect(url, token);
      } catch {
        if (!isMounted) return;
        setConnectionState("error");
        addTranscriptMessage("Sistema", "Erro ao conectar na sala.");
      }
    }

    connect();

    return () => {
      isMounted = false;
      cleanupAudioPipeline(room);
      if (room && room.state !== ConnectionState.Disconnected) {
        room.disconnect();
      }
    };
  }, [addTranscriptMessage, cleanupAudioPipeline, guestName, initializeMicrophone, roomName]);

  const toggleMute = async () => {
    const capture = nativeCaptureRef.current;
    if (!capture) return;
    const newMutedState = !isMuted;
    try {
      if (newMutedState) {
        await capture.localTrack.mute();
        capture.sourceTrack.enabled = false;
      } else {
        capture.sourceTrack.enabled = true;
        await capture.localTrack.unmute();
      }
      setIsMuted(newMutedState);
      setMicActive(!newMutedState);
      if (newMutedState) setMicLevel(0);
    } catch {}
  };

  const handleLeave = () => {
    cleanupAudioPipeline(roomRef.current);
    roomRef.current?.disconnect();
    router.push("/");
  };

  const formatTime = (s: number) =>
    `${Math.floor(s / 60)
      .toString()
      .padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;

  // Guards
  if (connectionState === "disconnected") {
    return (
      <div className="h-screen flex flex-col items-center justify-center bg-[#030712] gap-4">
        <div className="w-16 h-16 rounded-full bg-[#d4af37]/10 border border-[#d4af37]/30 flex items-center justify-center">
          <LogOut className="w-8 h-8 text-[#d4af37]" />
        </div>
        <h2 className="text-xl font-bold text-white">Sessão Encerrada</h2>
        <p className="text-sm text-gray-400">
          O anfitrião encerrou esta sessão de mentoria.
        </p>
        <button
          onClick={() => router.push("/")}
          className="mt-4 px-6 py-2.5 rounded-xl bg-[#d4af37] text-[#030712] font-bold text-sm hover:bg-[#b08d24] transition-colors"
        >
          Voltar ao Início
        </button>
      </div>
    );
  }

  const agentsList = Object.values(AGENTS_MAP);
  const host = agentsList.find((a) => a.id === "host");
  const others = agentsList.filter((a) => a.id !== "host");
  const reorderedAgents =
    host && others.length >= 4
      ? [others[0], others[1], host, others[2], others[3]]
      : agentsList;

  const agents = reorderedAgents.map((a) => ({
    ...a,
    speaking: activeSpeakers.has(a.id),
    connected: connectedAgents.has(a.id),
  }));

  const connectionIcon = {
    connected: <Wifi className="w-3.5 h-3.5 text-emerald-400" />,
    connecting: (
      <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />
    ),
    reconnecting: (
      <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />
    ),
    error: <WifiOff className="w-3.5 h-3.5 text-red-400" />,
    disconnected: <WifiOff className="w-3.5 h-3.5 text-red-400" />,
  }[connectionState];

  return (
    <div className="h-screen flex flex-col bg-[#030712] overflow-hidden">
      <div
        ref={audioContainerRef}
        style={{
          position: "absolute",
          width: 0,
          height: 0,
          overflow: "hidden",
          pointerEvents: "none",
        }}
        aria-hidden="true"
      />

      {/* Top Bar */}
      <div className="flex items-center justify-between px-6 py-4 bg-[#030712]/40 backdrop-blur-2xl border-b border-white/5 shrink-0 z-20">
        <div className="flex items-center gap-4">
          <div className="relative w-10 h-10 rounded-lg bg-[#0a0a0f] border border-[#d4af37]/30 flex items-center justify-center p-1">
            <Image
              src="/logo-icon.svg?v=2"
              alt="Hive Mind"
              width={40}
              height={40}
              className="w-full h-full object-contain"
              style={{
                filter:
                  "brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)",
              }}
            />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white flex items-center gap-2">
              Hive Mind
              <span className="text-[10px] text-[#d4af37] bg-[#d4af37]/10 px-1.5 py-0.5 rounded-full border border-[#d4af37]/20 font-bold uppercase">
                Convidado
              </span>
            </h1>
            <p className="text-[11px] text-gray-500">
              {guestName} · {formatTime(elapsedTime)}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-black/40 border border-white/10">
            {connectionIcon}
            <span className="text-[10px] text-gray-400 font-medium capitalize">
              {connectionState === "connected"
                ? "Conectado"
                : connectionState === "connecting"
                ? "Conectando..."
                : connectionState === "reconnecting"
                ? "Reconectando..."
                : "Erro"}
            </span>
          </div>
          <button
            onClick={() => setShowTranscript(!showTranscript)}
            className={`p-2 rounded-lg border transition-all ${
              showTranscript
                ? "bg-[#d4af37]/10 border-[#d4af37]/30 text-[#d4af37]"
                : "bg-white/5 border-white/10 text-gray-400 hover:text-white"
            }`}
            title="Transcrição"
          >
            <MessageSquare className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Main */}
      <div className="flex-1 flex overflow-hidden">
        {/* Agents Grid */}
        <div className="flex-1 p-3 sm:p-4 overflow-hidden">
          <div className="hidden lg:grid grid-cols-5 gap-3 h-full">
            {agents.map((agent) => (
              <GuestAgentCard key={agent.id} agent={agent} />
            ))}
          </div>
          <div className="hidden md:grid lg:hidden grid-cols-3 grid-rows-2 gap-3 h-full">
            {agents.map((agent) => (
              <GuestAgentCard key={agent.id} agent={agent} />
            ))}
          </div>
          <div className="md:hidden grid grid-cols-2 gap-3 overflow-y-auto pb-4 h-full">
            {agents.map((agent) => (
              <GuestAgentCard key={agent.id} agent={agent} compact />
            ))}
          </div>
        </div>

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
                <h3 className="text-sm font-semibold text-white">
                  Transcrição
                </h3>
                <p className="text-xs text-gray-500">
                  {transcript.length} mensagens
                </p>
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
      <div className="flex items-center justify-center gap-4 px-4 py-4 bg-gray-900/80 backdrop-blur-sm shrink-0">
        {micError && (
          <div className="absolute bottom-20 left-1/2 -translate-x-1/2 px-4 py-2 rounded-xl bg-red-500/20 border border-red-500/30 text-red-300 text-xs font-medium backdrop-blur-sm z-30">
            {micError}
          </div>
        )}

        <motion.button
          whileTap={{ scale: 0.9 }}
          onClick={toggleMute}
          className={`relative w-12 h-12 rounded-full flex items-center justify-center transition-all ${
            isMuted || !micActive
              ? "bg-red-500/20 border border-red-500/50 text-red-400"
              : "bg-white/10 border border-white/10 text-white hover:bg-white/20"
          }`}
          title={isMuted ? "Ativar microfone" : "Silenciar microfone"}
        >
          {isMuted || !micActive ? (
            <MicOff className="w-5 h-5" />
          ) : (
            <Mic className="w-5 h-5" />
          )}
          {micActive && !isMuted && micLevel > 0.02 && (
            <motion.div
              className="absolute inset-0 rounded-full border-2 border-emerald-400/60 pointer-events-none"
              animate={{
                scale: 1 + micLevel * 0.5,
                opacity: Math.min(micLevel * 2, 0.8),
              }}
              transition={{ duration: 0.1 }}
            />
          )}
        </motion.button>

        <motion.button
          whileTap={{ scale: 0.9 }}
          onClick={handleLeave}
          className="w-14 h-12 rounded-full bg-gray-700 hover:bg-gray-600 text-white flex items-center justify-center transition-all"
          title="Sair da sala"
        >
          <LogOut className="w-5 h-5" />
        </motion.button>
      </div>
    </div>
  );
}

// ─── GuestAgentCard ──────────────────────────────────────────────────────────

function GuestAgentCard({
  agent,
  compact = false,
}: {
  agent: Omit<AgentInfo, "speaking"> & {
    speaking: boolean;
    connected?: boolean;
  };
  compact?: boolean;
}) {
  const Icon = agent.icon;

  return (
    <motion.div
      layout
      className={`relative rounded-3xl overflow-hidden border transition-all duration-700 ease-in-out bg-black/40 backdrop-blur-md ${
        compact ? "h-40" : "h-full"
      } ${
        agent.speaking
          ? "border-[#d4af37] shadow-[0_0_50px_rgba(212,175,55,0.25)] scale-[1.02] z-10"
          : agent.connected
          ? "border-white/10 hover:border-[#d4af37]/30"
          : "border-white/5 opacity-50 grayscale-[0.5]"
      }`}
    >
      <div
        className={`absolute inset-0 bg-linear-to-br ${agent.gradient} transition-opacity duration-1000 ${
          agent.speaking ? "opacity-20" : "opacity-5"
        }`}
      />

      <div className="absolute inset-0 flex items-center justify-center p-6 pb-20">
        <div className="relative group">
          {agent.speaking && (
            <>
              <motion.div
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1.5, opacity: 0 }}
                transition={{ duration: 2, repeat: Infinity }}
                className="absolute inset-0 rounded-full border-2 border-[#d4af37]/30"
              />
              <motion.div
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1.8, opacity: 0 }}
                transition={{ duration: 2, repeat: Infinity, delay: 0.6 }}
                className="absolute inset-0 rounded-full border-2 border-[#d4af37]/10"
              />
            </>
          )}

          <motion.div
            animate={
              agent.speaking
                ? {
                    scale: 1.05,
                    boxShadow: "0 0 40px rgba(212, 175, 55, 0.4)",
                  }
                : { scale: 1, boxShadow: "0 0 20px rgba(0, 0, 0, 0.5)" }
            }
            className={`${
              compact ? "w-16 h-16" : "w-32 h-32 lg:w-40 lg:h-40"
            } rounded-full bg-[#030712] border-2 ${
              agent.speaking ? "border-[#d4af37]" : "border-white/10"
            } flex items-center justify-center relative z-10 overflow-hidden`}
          >
            <div
              className={`absolute inset-0 bg-linear-to-br ${agent.gradient} opacity-20`}
            />
            <Icon
              className={`${
                compact ? "w-8 h-8" : "w-14 h-14 lg:w-20 lg:h-20"
              } ${
                agent.speaking ? "text-[#d4af37]" : "text-gray-400"
              } transition-colors`}
            />
          </motion.div>
        </div>
      </div>

      <div className="absolute top-4 left-4 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-black/40 backdrop-blur-md border border-white/10">
        <div
          className={`w-1.5 h-1.5 rounded-full ${
            agent.connected
              ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]"
              : "bg-gray-600"
          }`}
        />
        <span
          className={`text-[9px] font-bold uppercase tracking-wider ${
            agent.connected ? "text-emerald-400" : "text-gray-500"
          }`}
        >
          {agent.connected ? "Online" : "Standby"}
        </span>
      </div>

      {agent.speaking && (
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          className="absolute top-4 right-4 flex items-center gap-2 bg-[#d4af37] px-3 py-1 rounded-full shadow-[0_0_20px_rgba(212,175,55,0.3)]"
        >
          <div className="flex items-center gap-1">
            {[0, 1, 2].map((i) => (
              <motion.div
                key={i}
                animate={{ height: ["4px", "10px", "4px"] }}
                transition={{
                  duration: 0.5,
                  repeat: Infinity,
                  delay: i * 0.1,
                }}
                className="w-0.5 bg-[#030712] rounded-full"
              />
            ))}
          </div>
          <span className="text-[9px] font-black uppercase text-[#030712] tracking-tighter">
            Live Insight
          </span>
        </motion.div>
      )}

      <div className="absolute bottom-0 left-0 right-0 p-6 bg-linear-to-t from-[#030712] via-[#030712]/90 to-transparent">
        <div className="relative z-10 text-center">
          <h3
            className={`font-black text-white tracking-tight uppercase leading-none ${
              compact ? "text-[10px]" : "text-lg"
            }`}
          >
            {agent.name}
          </h3>
          <p
            className={`font-medium text-[#d4af37] tracking-widest uppercase mt-1.5 ${
              compact ? "text-[8px]" : "text-[10px]"
            }`}
          >
            {agent.role}
          </p>
        </div>
      </div>

      {agent.speaking && (
        <div className="absolute inset-x-0 bottom-0 h-1 gold-gradient shadow-[0_-10px_30px_rgba(212,175,55,0.5)]" />
      )}
    </motion.div>
  );
}
