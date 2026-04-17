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
  AlertCircle,
  UserPlus,
  VolumeX,
  Volume2,
  Link,
  Copy,
  Check
} from "lucide-react";
import {
  useState,
  useEffect,
  useRef,
  useCallback,
} from "react";
import Image from "next/image";
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
  RemoteVideoTrack,
} from "livekit-client";
import {
  buildAudioCaptureOptions,
  inspectAudioInputState,
  resolveMicrophoneError,
  type AudioDiagnosticsSnapshot,
  type AudioRuntimeLog,
} from "@/lib/audio/vad-monitor";
import {
  createNativeAudioCapture,
  type NativeAudioCapture,
} from "@/lib/audio/native-capture";

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

const DATA_PACKET_SCHEMA_VERSION = "1.0";

type AgentTurnStatus =
  | "idle"
  | "activated"
  | "running"
  | "completed"
  | "timeout"
  | "error"
  | "cancelled";

type ProtocolHealth = "ok" | "warn" | "error";

function initialTurnStatusState(): Record<string, AgentTurnStatus> {
  return Object.keys(AGENTS_MAP).reduce<Record<string, AgentTurnStatus>>(
    (acc, id) => {
      acc[id] = "idle";
      return acc;
    },
    {}
  );
}

function getTurnStatusLabel(status: AgentTurnStatus): string {
  switch (status) {
    case "activated":
      return "Ativado";
    case "running":
      return "Em execução";
    case "completed":
      return "Finalizado";
    case "timeout":
      return "Timeout";
    case "error":
      return "Erro";
    case "cancelled":
      return "Cancelado";
    default:
      return "Aguardando";
  }
}

function getTurnStatusClass(status: AgentTurnStatus): string {
  switch (status) {
    case "activated":
      return "text-cyan-300 border-cyan-500/40 bg-cyan-500/15";
    case "running":
      return "text-[#d4af37] border-[#d4af37]/40 bg-[#d4af37]/10";
    case "completed":
      return "text-emerald-300 border-emerald-500/40 bg-emerald-500/15";
    case "timeout":
      return "text-amber-300 border-amber-500/40 bg-amber-500/15";
    case "error":
      return "text-red-300 border-red-500/40 bg-red-500/15";
    case "cancelled":
      return "text-gray-300 border-gray-500/40 bg-gray-500/15";
    default:
      return "text-gray-400 border-white/10 bg-black/40";
  }
}

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
  const [activeVideoTracks, setActiveVideoTracks] = useState<Record<string, RemoteVideoTrack>>({});
  const [transcript, setTranscript] = useState<TranscriptMessage[]>([]);
  const [showTranscript, setShowTranscript] = useState(false);
  const [maxSessionTime, setMaxSessionTime] = useState<number | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [executionPlan, setExecutionPlan] = useState<string | null>(null);
  const [pdfBase64, setPdfBase64] = useState<string | null>(null);
  const [sessionDocuments, setSessionDocuments] = useState<Array<{ docType: string, title: string, content: string, pdfUrl: string | null }>>([]);
  const [showPlan, setShowPlan] = useState<boolean | "content" | "checklist">(false);
  // F4: Timeout de connecting
  const [connectingTooLong, setConnectingTooLong] = useState(false);
  const [connectingTimedOut, setConnectingTimedOut] = useState(false);

  // F5: Document / Knowledge Upload
  const [showUpload, setShowUpload] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [docs, setDocs] = useState<{ id: string, fileName: string, createdAt: string }[]>([]);

  // F7: Convite de Equipe (Guest)
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [inviteLinkCopied, setInviteLinkCopied] = useState(false);

  // F8: Pausar IA (mute da sala para debates humanos)
  const [aiPaused, setAiPaused] = useState(false);

  // F5: Status individual dos agentes conectados
  const [connectedAgents, setConnectedAgents] = useState<Set<string>>(new Set());
  const [agentTurnStatus, setAgentTurnStatus] = useState<Record<string, AgentTurnStatus>>(
    () => initialTurnStatusState()
  );
  const [protocolHealth, setProtocolHealth] = useState<ProtocolHealth>("ok");
  const [protocolMessage, setProtocolMessage] = useState<string>("Protocolo sincronizado");
  const unsupportedVersionRef = useRef<Set<string>>(new Set());
  const turnTimersRef = useRef<Map<string, number>>(new Map());
  const turnSequencerRef = useRef<Map<string, number>>(new Map());

  // F6: Estado real do microfone e feedback visual
  const [micActive, setMicActive] = useState(false);
  const [micLevel, setMicLevel] = useState(0); // 0..1 nível de volume
  const [micError, setMicError] = useState<string | null>(null);
  const [, setAudioDiagnostics] = useState<AudioDiagnosticsSnapshot | null>(null);
  const [, setAudioLogs] = useState<AudioRuntimeLog[]>([]);
  const preferredInputIdRef = useRef<string | null>(null);
  const nativeCaptureRef = useRef<NativeAudioCapture | null>(null);

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
  const handleSessionCompletedRef = useRef<(fullTranscript?: string) => void | Promise<void>>(
    () => undefined
  );

  const pushAudioLog = useCallback((entry: AudioRuntimeLog) => {
    const printer =
      entry.level === "error"
        ? console.error
        : entry.level === "warn"
          ? console.warn
          : console.log;
    printer(`[Audio][${entry.timestamp}] ${entry.message}`);
    setAudioLogs((prev) => [entry, ...prev].slice(0, 8));
  }, []);

  const refreshAudioInputProbe = useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) {
      return;
    }

    try {
      const probe = await inspectAudioInputState(preferredInputIdRef.current);
      preferredInputIdRef.current = probe.selectedDeviceId ?? preferredInputIdRef.current;
      setAudioDiagnostics((prev) => ({
        permissionState: probe.permissionState,
        requestedSampleRate: prev?.requestedSampleRate ?? 48_000,
        appliedSampleRate: prev?.appliedSampleRate ?? 48_000,
        sampleSize: prev?.sampleSize ?? 16,
        channelCount: prev?.channelCount ?? 1,
        latencyMs: prev?.latencyMs ?? null,
        echoCancellation: prev?.echoCancellation ?? null,
        noiseSuppression: prev?.noiseSuppression ?? null,
        autoGainControl: prev?.autoGainControl ?? null,
        voiceIsolation: prev?.voiceIsolation ?? null,
        selectedDeviceId: probe.selectedDeviceId,
        selectedDeviceLabel: probe.selectedDeviceLabel,
        availableDevices: probe.devices.length,
        micLevel: prev?.micLevel ?? 0,
        rmsDb: prev?.rmsDb ?? -100,
        peakDb: prev?.peakDb ?? -100,
        noiseFloorDb: prev?.noiseFloorDb ?? -72,
        snrDb: prev?.snrDb ?? 0,
        clippingRatio: prev?.clippingRatio ?? 0,
        voiceActive: prev?.voiceActive ?? false,
        health: prev?.health ?? "warning",
        updatedAt: prev?.updatedAt ?? Date.now(),
      }));
    } catch (error) {
      pushAudioLog({
        level: "warn",
        message: `Falha ao enumerar dispositivos de áudio: ${resolveMicrophoneError(error)}`,
        timestamp: new Date().toLocaleTimeString("pt-BR"),
      });
    }
  }, [pushAudioLog]);

  const cleanupAudioPipeline = useCallback((room?: Room | null) => {
    const capture = nativeCaptureRef.current;
    nativeCaptureRef.current = null;
    if (capture) {
      if (room && room.state === ConnectionState.Connected) {
        void room.localParticipant.unpublishTrack(capture.localTrack, false).catch(() => undefined);
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
          throw new Error("Sala ainda não conectada para publicar microfone.");
        }
        await new Promise((resolve) => setTimeout(resolve, 250));
        const probe = await inspectAudioInputState(preferredInputIdRef.current);
        preferredInputIdRef.current = probe.selectedDeviceId ?? preferredInputIdRef.current;

        const capture = await createNativeAudioCapture({
          deviceId: preferredInputIdRef.current,
          onLog: pushAudioLog,
          onDiagnostics: (snapshot) => {
            preferredInputIdRef.current = snapshot.selectedDeviceId ?? preferredInputIdRef.current;
            setAudioDiagnostics(snapshot);
            setMicLevel(snapshot.micLevel);
          },
        });

        nativeCaptureRef.current = capture;

        const publication = await room.localParticipant.publishTrack(capture.localTrack, {
          source: Track.Source.Microphone,
          dtx: false,
          red: false,
          forceStereo: false,
          stopMicTrackOnMute: false,
          preConnectBuffer: true,
        });

        setMicActive(true);
        setIsMuted(false);
        setMicError(null);
        pushAudioLog({
          level: "info",
          message: "Captura de áudio nativa (getUserMedia) iniciada e publicada no LiveKit.",
          timestamp: new Date().toLocaleTimeString("pt-BR"),
        });

        return publication;
      } catch (micError) {
        const capture = nativeCaptureRef.current;
        if (capture) {
          capture.cleanup();
          nativeCaptureRef.current = null;
        }
        const message = resolveMicrophoneError(micError);
        setMicError(message);
        setMicActive(false);
        pushAudioLog({
          level: "error",
          message: `Falha ao ativar microfone: ${message}`,
          timestamp: new Date().toLocaleTimeString("pt-BR"),
        });
        throw micError;
      }
    },
    [cleanupAudioPipeline, pushAudioLog],
  );

  // Redireciona para login se não autenticado (executa apenas quando authStatus muda)
  useEffect(() => {
    if (authStatus === "unauthenticated") {
      router.replace("/login");
    }
  }, [authStatus, router]);

  useEffect(() => {
    void refreshAudioInputProbe();

    if (typeof navigator === "undefined" || !navigator.mediaDevices?.addEventListener) {
      return;
    }

    const handleDeviceChange = () => {
      pushAudioLog({
        level: "info",
        message: "Alteração detectada na lista de dispositivos de áudio.",
        timestamp: new Date().toLocaleTimeString("pt-BR"),
      });
      void refreshAudioInputProbe();
    };

    navigator.mediaDevices.addEventListener("devicechange", handleDeviceChange);

    return () => {
      navigator.mediaDevices.removeEventListener("devicechange", handleDeviceChange);
    };
  }, [pushAudioLog, refreshAudioInputProbe]);

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

  // F9: Forçar encerramento quando atingir tempo limite da assinatura (Billing Check)
  useEffect(() => {
    if (maxSessionTime && elapsedTime >= maxSessionTime && !ending) {
      console.warn(`[Timer] Limite da assinatura atingido (${maxSessionTime}s). Encerrando compulsoriamente.`);
      void handleEndSession();
    }
  }, [elapsedTime, maxSessionTime, ending]);

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
    const turnTimers = turnTimersRef.current;

    const clearTurnTimer = (agentId: string) => {
      const timer = turnTimers.get(agentId);
      if (timer) {
        window.clearTimeout(timer);
        turnTimers.delete(agentId);
      }
    };

    const scheduleTurnStatus = (
      agentId: string,
      status: AgentTurnStatus,
      delayMs: number
    ) => {
      clearTurnTimer(agentId);
      const timer = window.setTimeout(() => {
        setAgentTurnStatus((prev) => ({ ...prev, [agentId]: status }));
        turnTimers.delete(agentId);
      }, delayMs);
      turnTimers.set(agentId, timer);
    };
    let isMounted = true;
    const audioContainer = audioContainerRef.current;

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
        const participantIdentity = `user-${userId}-${Date.now()}`;
        const tokenRes = await safeFetch("/api/livekit/token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            roomName,
            participantName: userName,
            participantIdentity,
          }),
        });
        if (!isMounted) return;

        const { token, url, maxDurationSeconds } = await tokenRes.json();
        if (maxDurationSeconds) {
          setMaxSessionTime(maxDurationSeconds);
        }
        sessionDataRef.current = { ...sessionDataRef.current, token, url };

        // Configura a sala
        // CORREÇÃO VOZ: removido webAudioMix (causa AudioContext suspenso em mobile/iOS)
        room = new Room({
          adaptiveStream: true,
          dynacast: true,
          // IMPORTANTE: não desconecta quando a aba é minimizada
          disconnectOnPageLeave: false,
          // Reconexão automática com delays progressivos
          reconnectPolicy: new DefaultReconnectPolicy(
            [500, 1000, 2000, 5000, 10000, 30000]
          ),
          audioCaptureDefaults: buildAudioCaptureOptions(),
          publishDefaults: {
            dtx: true,
            red: true,
            preConnectBuffer: true,
            stopMicTrackOnMute: false,
            audioPreset: { maxBitrate: 32000 },
          },
        });

        // ── Eventos da sala ──────────────────────────────────────────────────

        room.on(RoomEvent.Connected, async () => {
          if (!isMounted) return;
          roomRef.current = room;
          setConnectionState("connected");
          setConnectedAgents((prev) => new Set(prev).add("host"));
          addTranscriptMessage("Sistema", "Conectado! Aguardando os especialistas...");

          // CORREÇÃO VOZ: Desbloqueia AudioContext do browser automaticamente
          // Sem isso, browsers modernos podem suspender o áudio silenciosamente
          try {
            await room!.startAudio();
            console.log("[LiveKit] AudioContext desbloqueado com sucesso.");
          } catch (audioErr) {
            console.warn("[LiveKit] Falha ao desbloquear AudioContext:", audioErr);
          }

          try {
            const payload = new TextEncoder().encode(
              JSON.stringify({ type: "set_user_name", name: userName }),
            );
            await room!.localParticipant.publishData(payload, { reliable: true });
          } catch (error) {
            console.warn("[Room] Não foi possível sincronizar nome do usuário com o worker:", error);
          }

          for (const [, p] of room!.remoteParticipants) {
            const pid = p.identity;
            if (pid.startsWith("agent-")) {
              const agId = pid.replace("agent-", "");
              if (AGENTS_MAP[agId]) {
                setConnectedAgents((prev) => new Set(prev).add(agId));
              }
            }
          }

          let micEnabled = false;
          for (let attempt = 0; attempt < 2 && !micEnabled; attempt++) {
            try {
              await initializeMicrophone(room!);
              micEnabled = true;
              console.log(`[LiveKit] Microfone ativado com sucesso (tentativa ${attempt + 1}).`);
            } catch (micErr) {
              console.warn(`[LiveKit] Erro ao ativar microfone (tentativa ${attempt + 1}/3):`, micErr);
              if (attempt < 1) await new Promise(r => setTimeout(r, 1000));
              else {
                setMicError(resolveMicrophoneError(micErr));
                setMicActive(false);
              }
            }
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
          const payload = new TextEncoder().encode(
            JSON.stringify({ type: "set_user_name", name: userName }),
          );
          void room?.localParticipant.publishData(payload, { reliable: true }).catch(() => undefined);
          if (!room?.localParticipant.getTrackPublication(Track.Source.Microphone)) {
            void initializeMicrophone(room!);
          }
        });

        room.on(RoomEvent.MediaDevicesError, (error) => {
          const message = resolveMicrophoneError(error);
          setMicError(message);
          setMicActive(false);
          pushAudioLog({
            level: "error",
            message,
            timestamp: new Date().toLocaleTimeString("pt-BR"),
          });
        });

        room.on(RoomEvent.LocalTrackPublished, (publication) => {
          if (publication.source === Track.Source.Microphone) {
            pushAudioLog({
              level: "info",
              message: "Trilha de microfone publicada com sucesso no LiveKit.",
              timestamp: new Date().toLocaleTimeString("pt-BR"),
            });
          }
        });

        room.on(RoomEvent.LocalTrackUnpublished, (publication) => {
          if (publication.source === Track.Source.Microphone) {
            pushAudioLog({
              level: "warn",
              message: "Trilha de microfone removida da sessão.",
              timestamp: new Date().toLocaleTimeString("pt-BR"),
            });
          }
        });

        room.on(RoomEvent.TrackMuted, (_publication, participant) => {
          if (participant.isLocal) {
            setMicActive(false);
          }
        });

        room.on(RoomEvent.TrackUnmuted, (_publication, participant) => {
          if (participant.isLocal) {
            setMicActive(true);
          }
        });

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
            } else if (track.kind === Track.Kind.Video && participant.identity.startsWith("bey-")) {
              let agId = participant.identity.replace("bey-", "");
              if (agId.startsWith("agent-")) agId = agId.replace("agent-", "");

              setActiveVideoTracks((prev) => ({ ...prev, [agId]: track as RemoteVideoTrack }));
              console.log(`[Video] Câmera do avatar ${agId} recebida e registrada.`);
            }
          }
        );

        room.on(
          RoomEvent.TrackUnsubscribed,
          (track, _pub, participant: RemoteParticipant) => {
            if (track.kind === Track.Kind.Audio) {
              audioContainerRef.current
                ?.querySelector(`#audio-${participant.identity}`)
                ?.remove();
              track.detach();
            } else if (track.kind === Track.Kind.Video && participant.identity.startsWith("bey-")) {
              let agId = participant.identity.replace("bey-", "");
              if (agId.startsWith("agent-")) agId = agId.replace("agent-", "");

              setActiveVideoTracks((prev) => {
                const next = { ...prev };
                delete next[agId];
                return next;
              });
              console.log(`[Video] Câmera do avatar ${agId} removida.`);
            }
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
              const packetVersion = typeof data.version === "string" ? data.version : null;

              if (packetVersion && packetVersion !== DATA_PACKET_SCHEMA_VERSION) {
                if (!unsupportedVersionRef.current.has(packetVersion)) {
                  unsupportedVersionRef.current.add(packetVersion);
                  setProtocolHealth("error");
                  setProtocolMessage(`Versão incompatível: ${packetVersion}`);
                  addTranscriptMessage(
                    "Sistema",
                    `Pacote ignorado por versão incompatível (${packetVersion}). Esperado ${DATA_PACKET_SCHEMA_VERSION}.`
                  );
                }
                return;
              }

              if (!packetVersion) {
                setProtocolHealth((prev) => (prev === "error" ? prev : "warn"));
                setProtocolMessage((prev) =>
                  prev.startsWith("Versão incompatível")
                    ? prev
                    : "Recebendo pacotes sem versão (modo compatível)"
                );
              } else if (packetVersion === DATA_PACKET_SCHEMA_VERSION) {
                setProtocolHealth((prev) => (prev === "error" ? prev : "ok"));
                setProtocolMessage("Protocolo sincronizado");
              }

              if (data.type === "transcript") {
                addTranscriptMessage(data.speaker, data.text);
              } else if (data.type === "execution_plan") {
                setExecutionPlan(data.plan ?? data.text ?? "");
                // Captura o PDF Base64 enviado pelo Marco via LiveKit packet
                if (data.pdf_base64 && typeof data.pdf_base64 === "string") {
                  setPdfBase64(data.pdf_base64);
                }
                setSessionDocuments(prev => [...prev, {
                  docType: "plano_execucao",
                  title: "Plano de Execução",
                  content: data.plan ?? data.text ?? "",
                  pdfUrl: data.pdf_base64 || null
                }]);
                setShowPlan(true);
                addTranscriptMessage(
                  "Marco",
                  data.pdf_base64
                    ? "Plano de Execução gerado! PDF disponível para download."
                    : "Plano de Execução gerado!"
                );
              } else if (data.type === "document_ready") {
                // Novos documentos do Marco (SWOT, Canvas, Pitch, Contrato, etc.)
                const docTitle = (data.doc_title as string) || "Documento";
                const docType = (data.doc_type as string) || "custom";
                setExecutionPlan(data.plan ?? data.text ?? "");
                if (data.pdf_base64 && typeof data.pdf_base64 === "string") {
                  setPdfBase64(data.pdf_base64);
                }
                setSessionDocuments(prev => [...prev, {
                  docType: docType,
                  title: docTitle,
                  content: data.plan ?? data.text ?? "",
                  pdfUrl: data.pdf_base64 || null
                }]);
                setShowPlan(true);
                // Atualiza o nome do botão de download com o tipo do documento
                if (typeof window !== "undefined") {
                  const downloadBtn = document.querySelector<HTMLAnchorElement>("[data-marco-download]");
                  if (downloadBtn) {
                    downloadBtn.download = `${docTitle.replace(/\s+/g, "_")}_HiveMind.pdf`;
                    downloadBtn.setAttribute("data-doc-title", docTitle);
                  }
                }
                addTranscriptMessage(
                  "Marco",
                  data.pdf_base64
                    ? `✅ ${docTitle} pronto! PDF disponível para download.`
                    : `✅ ${docTitle} preparado!`
                );
              } else if (data.type === "marco_working") {
                // Progresso em tempo real do Marco trabalhando nos bastidores
                const status = (data.status as string) || "Marco está trabalhando...";
                const progress = typeof data.progress === "number" ? data.progress : 0;
                if (progress < 100) {
                  addTranscriptMessage("Marco (bastidores)", `⚙️ ${status}`);
                }

              } else if (data.type === "session_end") {
                void handleSessionCompletedRef.current?.(data.transcript);
              } else if (data.type === "agent_ready") {
                // F5: Marca o agente como conectado quando recebe health-check do backend
                const agentId = data.agent_id as string;
                if (agentId) {
                  setConnectedAgents((prev) => new Set(prev).add(agentId));
                }
              } else if (data.type === "agent_activated") {
                const agentId = data.agent_id as string;
                const turnId =
                  typeof data.turn_id === "number" ? data.turn_id : Date.now();
                if (agentId) {
                  const lastTurn = turnSequencerRef.current.get(agentId) ?? -1;
                  if (turnId >= lastTurn) {
                    turnSequencerRef.current.set(agentId, turnId);
                    setAgentTurnStatus((prev) => ({ ...prev, [agentId]: "activated" }));
                    scheduleTurnStatus(agentId, "running", 1200);
                  }
                }
              } else if (data.type === "agent_done") {
                const agentId = data.agent_id as string;
                const turnId =
                  typeof data.turn_id === "number" ? data.turn_id : Date.now();
                if (agentId) {
                  const lastTurn = turnSequencerRef.current.get(agentId) ?? -1;
                  if (turnId >= lastTurn) {
                    turnSequencerRef.current.set(agentId, turnId);
                    clearTurnTimer(agentId);
                    setAgentTurnStatus((prev) => ({ ...prev, [agentId]: "completed" }));
                    scheduleTurnStatus(agentId, "idle", 6000);
                  }
                }
              } else if (data.type === "agent_timeout") {
                const agentId = data.agent_id as string;
                if (agentId) {
                  clearTurnTimer(agentId);
                  setAgentTurnStatus((prev) => ({ ...prev, [agentId]: "timeout" }));
                  scheduleTurnStatus(agentId, "idle", 9000);
                }
              } else if (data.type === "agent_error") {
                const agentId = data.agent_id as string;
                if (agentId) {
                  clearTurnTimer(agentId);
                  setAgentTurnStatus((prev) => ({ ...prev, [agentId]: "error" }));
                  scheduleTurnStatus(agentId, "idle", 9000);
                }
              } else if (data.type === "agent_cancelled") {
                const agentId = data.agent_id as string;
                if (agentId) {
                  clearTurnTimer(agentId);
                  setAgentTurnStatus((prev) => ({ ...prev, [agentId]: "cancelled" }));
                  scheduleTurnStatus(agentId, "idle", 5000);
                }
              } else if (data.type === "agent_transferred") {
                // Transferência lateral entre especialistas
                const sourceAgentId = data.agent_id as string;
                const targetAgentId = data.target_agent_id as string;
                const fromName = data.from_name as string || "";
                const targetName = targetAgentId ? (AGENTS_MAP[targetAgentId]?.name || targetAgentId) : "";
                if (sourceAgentId) {
                  clearTurnTimer(sourceAgentId);
                  setAgentTurnStatus((prev) => ({ ...prev, [sourceAgentId]: "completed" }));
                  scheduleTurnStatus(sourceAgentId, "idle", 4000);
                }
                if (targetAgentId) {
                  setAgentTurnStatus((prev) => ({ ...prev, [targetAgentId]: "activated" }));
                  scheduleTurnStatus(targetAgentId, "running", 1200);
                }
                if (fromName && targetName) {
                  addTranscriptMessage("Sistema", `${fromName} passou a palavra para ${targetName}.`);
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
      turnTimers.forEach((timer) => window.clearTimeout(timer));
      turnTimers.clear();

      cleanupAudioPipeline(room);

      if (room && room.state !== ConnectionState.Disconnected) {
        room.disconnect();
      }
      audioContainer
        ?.querySelectorAll("audio")
        .forEach((el) => el.remove());
    };
  }, [addTranscriptMessage, authStatus, cleanupAudioPipeline, initializeMicrophone, projectId, pushAudioLog, session]);

  // ─── Handlers ───────────────────────────────────────────────────────────────

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
      if (newMutedState) {
        setMicLevel(0);
      }
      setMicError(null);
    } catch (err) {
      console.warn("[LiveKit] Erro ao alternar microfone:", err);
      setMicError(resolveMicrophoneError(err));
    }
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
              documents: sessionDocuments,
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
              documents: sessionDocuments,
            }),
          });
        } catch (err) {
          console.error("[Sessão] Falha ao finalizar automaticamente:", err);
        }
      }
      roomRef.current?.disconnect();
      router.push("/dashboard");
    },
    [sessionId, transcript, executionPlan, pdfBase64, router]
  );

  useEffect(() => {
    handleSessionCompletedRef.current = handleSessionCompleted;
  }, [handleSessionCompleted]);

  // ─── Guards de render ────────────────────────────────────────────────────────

  if (authStatus === "loading") {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-950">
        <Loader2 className="w-8 h-8 text-[#d4af37] animate-spin" />
      </div>
    );
  }

  if (authStatus === "unauthenticated") return null;

  const agentsList = Object.values(AGENTS_MAP);
  const host = agentsList.find(a => a.id === "host");
  const others = agentsList.filter(a => a.id !== "host");

  // Reordena para colocar o host no centro: 2 agentes, host, 2 agentes
  const reorderedAgents = host && others.length >= 4
    ? [others[0], others[1], host, others[2], others[3]]
    : agentsList;

  const agents = reorderedAgents.map((a) => ({
    ...a,
    speaking: activeSpeakers.has(a.id),
    connected: connectedAgents.has(a.id),
    turnStatus: agentTurnStatus[a.id] ?? "idle",
    videoTrack: activeVideoTracks[a.id],
  }));

  const connectionIcon = {
    connected: <Wifi className="w-3.5 h-3.5 text-emerald-400" />,
    connecting: <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />,
    reconnecting: <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />,
    error: <WifiOff className="w-3.5 h-3.5 text-red-400" />,
  }[connectionState];

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="h-screen flex flex-col bg-[#030712] overflow-hidden">
      {/*
        CORREÇÃO P1 / P6: container oculto para elementos de áudio.
        Fica dentro da árvore React → cleanup garantido no unmount.
      */}
      <div ref={audioContainerRef} style={{ position: 'absolute', width: 0, height: 0, overflow: 'hidden', pointerEvents: 'none' }} aria-hidden="true" />

      {/* Top Bar */}
      <div className="flex items-center justify-between px-6 py-4 bg-[#030712]/40 backdrop-blur-2xl border-b border-white/5 shrink-0 z-20">
        <div className="flex items-center gap-4">
          <div className="relative group">
            <div className="absolute -inset-0.5 bg-[#d4af37]/30 rounded-lg blur opacity-50 group-hover:opacity-100 transition-opacity" />
            <div className="relative w-12 h-12 rounded-lg bg-[#0a0a0f] border border-[#d4af37]/30 flex items-center justify-center p-1 group-hover:border-[#d4af37]/60 transition-all">
              <Image src="/logo-icon.svg?v=2" alt="Hive Mind" width={48} height={48} className="w-full h-full object-contain" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
            </div>
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight uppercase bg-linear-to-r from-[#d4af37] to-[#f0dfa0] bg-clip-text text-transparent">Sala de Mentoria de Elite</h1>
            <p className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold mt-0.5">Comitê Executivo Hive Mind</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/5">
            {connectionIcon}
            {connectionState === "reconnecting" && (
              <span className="text-[10px] text-amber-400 font-bold uppercase tracking-wider">Reconectando</span>
            )}
            <div className="h-3 w-px bg-white/10" />
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse shadow-[0_0_8px_rgba(239,68,68,0.5)]" />
              <span className="text-[11px] text-gray-400 font-mono font-bold tracking-tighter">
                {formatTime(elapsedTime)}
              </span>
            </div>
          </div>
          <div className={`hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full border text-[10px] font-bold uppercase tracking-wider ${protocolHealth === "error"
              ? "bg-red-500/10 border-red-500/30 text-red-300"
              : protocolHealth === "warn"
                ? "bg-amber-500/10 border-amber-500/30 text-amber-300"
                : "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
            }`}>
            <span>{protocolHealth === "ok" ? "Protocolo OK" : protocolHealth === "warn" ? "Compatível" : "Incompatível"}</span>
            <span className="text-[9px] normal-case tracking-normal opacity-80">{protocolMessage}</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowUpload(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all bg-white/5 text-gray-400 hover:text-[#d4af37] hover:bg-white/10 border border-transparent hover:border-[#d4af37]/20"
              title="Anexos do Negócio"
            >
              <Paperclip className="w-3.5 h-3.5" />
              <span className="hidden sm:inline uppercase tracking-tighter">Anexos</span>
            </button>

            {executionPlan && (
              <button
                onClick={() => setShowPlan((v) => !v)}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all shadow-xl ${showPlan
                  ? "bg-violet-600/30 text-violet-200 border border-violet-500/50 shadow-violet-500/10"
                  : "bg-white/5 text-gray-400 hover:text-white border border-transparent"
                  }`}
              >
                <FileText className="w-3.5 h-3.5" />
                <span className="uppercase tracking-tighter">Plano Final</span>
              </button>
            )}

            {pdfBase64 && (
              <a
                href={`data:application/pdf;base64,${pdfBase64}`}
                download="Documento_Estrategico_HiveMind.pdf"
                data-marco-download="true"
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all bg-[#d4af37]/15 text-[#d4af37] hover:bg-[#d4af37]/25 border border-[#d4af37]/30 hover:border-[#d4af37]/60 shadow-[0_0_20px_rgba(212,175,55,0.1)] hover:shadow-[0_0_30px_rgba(212,175,55,0.2)]"
                title="Baixar PDF"
              >
                <Star className="w-3.5 h-3.5" />
                <span className="uppercase tracking-tighter hidden sm:inline">PDF</span>
              </a>
            )}

            <button
              onClick={() => setShowTranscript((v) => !v)}
              className={`p-2.5 rounded-xl transition-all border ${showTranscript
                ? "bg-[#d4af37]/10 text-[#d4af37] border-[#d4af37]/30 shadow-[0_0_20px_rgba(212,175,55,0.1)]"
                : "bg-white/5 text-gray-400 hover:text-white border-transparent hover:bg-white/10"
                }`}
            >
              <MessageSquare className="w-4.5 h-4.5" />
            </button>
          </div>
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
          {/* Desktop/Tablet Layout: 5 colunas formato retrato com apresentadora no centro */}
          <div className="hidden lg:grid grid-cols-5 gap-3 h-full">
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
          {/* Tablet Landscape */}
          <div className="hidden md:grid lg:hidden grid-cols-3 grid-rows-2 gap-3 h-full">
            {agents.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
          {/* Mobile Layout */}
          <div className="md:hidden grid grid-cols-2 gap-3 overflow-y-auto pb-4 h-full">
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
      <div className="flex items-center justify-center gap-4 px-4 py-4 bg-gray-900/80 backdrop-blur-sm shrink-0">
        {micError && (
          <div className="absolute bottom-20 left-1/2 -translate-x-1/2 px-4 py-2 rounded-xl bg-red-500/20 border border-red-500/30 text-red-300 text-xs font-medium flex items-center gap-2 backdrop-blur-sm z-30">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            {micError}
          </div>
        )}

        <motion.button
          whileTap={{ scale: 0.9 }}
          onClick={toggleMute}
          className={`relative w-12 h-12 rounded-full flex items-center justify-center transition-all ${isMuted || !micActive
            ? "bg-red-500/20 border border-red-500/50 text-red-400"
            : "bg-white/10 border border-white/10 text-white hover:bg-white/20"
            }`}
          title={isMuted ? "Ativar microfone" : "Silenciar microfone"}
        >
          {isMuted || !micActive ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}

          {/* CORREÇÃO VOZ: Indicador visual de nível de áudio */}
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

          {/* Anel pulsante quando o mic está ativo */}
          {micActive && !isMuted && (
            <div className="absolute -bottom-1 left-1/2 -translate-x-1/2">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.6)]" />
            </div>
          )}
        </motion.button>

        {/* Botão Convidar Equipe */}
        <motion.button
          whileTap={{ scale: 0.9 }}
          onClick={() => setShowInviteModal(true)}
          className="w-12 h-12 rounded-full bg-white/10 border border-white/10 text-white hover:bg-[#d4af37]/20 hover:border-[#d4af37]/30 hover:text-[#d4af37] flex items-center justify-center transition-all"
          title="Convidar equipe"
        >
          <UserPlus className="w-5 h-5" />
        </motion.button>

        {/* Botão Pausar IA */}
        <motion.button
          whileTap={{ scale: 0.9 }}
          onClick={() => {
            const newVal = !aiPaused;
            setAiPaused(newVal);
            if (roomRef.current) {
              const enc = new TextEncoder();
              roomRef.current.localParticipant.publishData(
                enc.encode(JSON.stringify({
                  version: DATA_PACKET_SCHEMA_VERSION,
                  type: newVal ? "pause_ai" : "resume_ai",
                })),
                { reliable: true }
              );
            }
            addTranscriptMessage("Sistema", newVal
              ? "IA pausada — os agentes estão em silêncio durante o debate."
              : "IA ativa novamente — os agentes podem participar."
            );
          }}
          className={`w-12 h-12 rounded-full flex items-center justify-center transition-all ${aiPaused
              ? "bg-amber-500/20 border border-amber-500/50 text-amber-400"
              : "bg-white/10 border border-white/10 text-white hover:bg-white/20"
            }`}
          title={aiPaused ? "Reativar IA" : "Pausar IA (modo debate)"}
        >
          {aiPaused ? <VolumeX className="w-5 h-5" /> : <Volume2 className="w-5 h-5" />}
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

      {/* Modal de Convite */}
      <AnimatePresence>
        {showInviteModal && (
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
              <div className="w-16 h-16 rounded-full bg-[#d4af37]/10 border border-[#d4af37]/20 flex items-center justify-center mx-auto mb-4">
                <UserPlus className="w-8 h-8 text-[#d4af37]" />
              </div>
              <h2 className="text-xl font-bold text-white mb-2">
                Convidar Equipe
              </h2>
              <p className="text-sm text-gray-400 mb-6">
                Compartilhe o link abaixo para que até 3 membros da sua equipe participem da mentoria como convidados.
              </p>

              <div className="flex items-center gap-2 bg-black/40 border border-white/10 rounded-xl px-4 py-3 mb-4">
                <Link className="w-4 h-4 text-gray-500 shrink-0" />
                <input
                  readOnly
                  value={typeof window !== "undefined" ? `${window.location.origin}/join/${projectId}` : ""}
                  className="flex-1 bg-transparent text-sm text-gray-300 outline-none truncate font-mono"
                />
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(`${window.location.origin}/join/${projectId}`);
                    setInviteLinkCopied(true);
                    setTimeout(() => setInviteLinkCopied(false), 2000);
                  }}
                  className="shrink-0 px-3 py-1.5 rounded-lg bg-[#d4af37]/20 border border-[#d4af37]/30 text-[#d4af37] text-xs font-semibold hover:bg-[#d4af37]/30 transition-colors flex items-center gap-1.5"
                >
                  {inviteLinkCopied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                  {inviteLinkCopied ? "Copiado!" : "Copiar"}
                </button>
              </div>

              <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/20 mb-6">
                <AlertCircle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                <p className="text-[11px] text-amber-400/80 text-left">
                  Convidados podem ouvir e falar, mas não possuem controle administrativo da sessão.
                </p>
              </div>

              <button
                onClick={() => setShowInviteModal(false)}
                className="px-6 py-2.5 rounded-xl bg-white/5 border border-white/10 text-gray-300 hover:bg-white/10 transition-colors text-sm"
              >
                Fechar
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

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
        <div className="fixed inset-0 z-60 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
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
      const topOrdered = !!olMatch;
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

  const toggleItem = (id: string) => {
    setChecklist((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, completed: !item.completed } : item
      )
    );
  };

  const completedCount = checklist.filter((item) => item.completed).length;
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
            className="h-full bg-linear-to-r from-emerald-500 to-teal-400"
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
  agent: AgentInfo & { connected?: boolean; turnStatus?: AgentTurnStatus; videoTrack?: RemoteVideoTrack };
  compact?: boolean;
}) {
  const Icon = agent.icon;
  const turnStatus = agent.turnStatus ?? "idle";
  const turnLabel = getTurnStatusLabel(turnStatus);
  const turnClass = getTurnStatusClass(turnStatus);

  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (agent.videoTrack && videoRef.current) {
      agent.videoTrack.attach(videoRef.current);
      return () => {
        agent.videoTrack?.detach();
      };
    }
  }, [agent.videoTrack]);

  return (
    <motion.div
      layout
      className={`relative rounded-3xl overflow-hidden border transition-all duration-700 ease-in-out bg-black/40 backdrop-blur-md ${compact ? "h-40" : "h-full"
        } ${agent.speaking
          ? "border-[#d4af37] shadow-[0_0_50px_rgba(212,175,55,0.25)] scale-[1.02] z-10"
          : agent.connected
            ? "border-white/10 hover:border-[#d4af37]/30"
            : "border-white/5 opacity-50 grayscale-[0.5]"
        }`}
    >
      {/* Background Glow */}
      <div
        className={`absolute inset-0 bg-linear-to-br ${agent.gradient} transition-opacity duration-1000 ${agent.speaking ? 'opacity-20' : 'opacity-5'
          }`}
      />

      {/* Abstract Pattern Layer */}
      <div className="absolute inset-0 opacity-[0.03] pointer-events-none bg-[url('https://www.transparenttextures.com/patterns/carbon-fibre.png')]" />

      {/* Avatar Container */}
      <div className="absolute inset-0 flex items-center justify-center p-6 pb-20">
        <div className="relative group">
          {/* Animated Rings for Speaking */}
          {agent.speaking && (
            <>
              <motion.div
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1.5, opacity: 0 }}
                transition={{ duration: 2, repeat: Infinity }}
                className={`absolute inset-0 rounded-full border-2 border-[#d4af37]/30`}
              />
              <motion.div
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1.8, opacity: 0 }}
                transition={{ duration: 2, repeat: Infinity, delay: 0.6 }}
                className={`absolute inset-0 rounded-full border-2 border-[#d4af37]/10`}
              />
            </>
          )}

          <motion.div
            animate={
              agent.speaking
                ? { scale: 1.05, boxShadow: "0 0 40px rgba(212, 175, 55, 0.4)" }
                : { scale: 1, boxShadow: "0 0 20px rgba(0, 0, 0, 0.5)" }
            }
            className={`${compact ? "w-16 h-16" : "w-32 h-32 lg:w-40 lg:h-40"
              } rounded-full bg-[#030712] border-2 ${agent.speaking ? 'border-[#d4af37]' : 'border-white/10'
              } flex items-center justify-center relative z-10 overflow-hidden group-hover:border-[#d4af37]/50 transition-colors`}
          >
            <div className={`absolute inset-0 bg-linear-to-br ${agent.gradient} opacity-[0.15] z-0`} />

            {/* Feed de vídeo realista do Beyond Presence */}
            {agent.videoTrack && (
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="absolute inset-0 w-full h-full object-cover z-10"
              />
            )}

            {/* Ícone vetorizado clássico (Exibição Fallback) */}
            {!agent.videoTrack && (
              <Icon
                className={`${compact ? "w-8 h-8" : "w-14 h-14 lg:w-20 lg:h-20"
                  } ${agent.speaking ? 'text-[#d4af37]' : 'text-gray-400 group-hover:text-gray-300'} transition-colors relative z-20`}
              />
            )}

            {/* Overlay sutil quando está falando por cima do vídeo */}
            {agent.videoTrack && agent.speaking && (
              <div className="absolute inset-0 bg-[#d4af37]/10 z-20 mix-blend-overlay pointer-events-none" />
            )}
          </motion.div>
        </div>
      </div>

      <div className="absolute top-4 left-4 right-4 flex justify-between items-start z-20">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-black/40 backdrop-blur-md border border-white/10">
            <div className={`w-1.5 h-1.5 rounded-full ${agent.connected ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]' : 'bg-gray-600'}`} />
            <span className={`text-[9px] font-bold uppercase tracking-wider ${agent.connected ? 'text-emerald-400' : 'text-gray-500'}`}>
              {agent.connected ? 'Online' : 'Standby'}
            </span>
          </div>
          <div className={`px-2.5 py-1 rounded-full border text-[9px] font-bold uppercase tracking-wider ${turnClass}`}>
            {turnLabel}
          </div>
        </div>

        {agent.speaking && (
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-center gap-2 bg-[#d4af37] px-3 py-1 rounded-full shadow-[0_0_20px_rgba(212,175,55,0.3)]"
          >
            <div className="flex items-center gap-1">
              {[0, 1, 2].map((i) => (
                <motion.div
                  key={i}
                  animate={{ height: ["4px", "10px", "4px"] }}
                  transition={{ duration: 0.5, repeat: Infinity, delay: i * 0.1 }}
                  className="w-0.5 bg-[#030712] rounded-full"
                />
              ))}
            </div>
            <span className="text-[9px] font-black uppercase text-[#030712] tracking-tighter">Live Insight</span>
          </motion.div>
        )}
      </div>

      {/* Info Overlay */}
      <div className="absolute bottom-0 left-0 right-0 p-6 bg-linear-to-t from-[#030712] via-[#030712]/90 to-transparent">
        <div className="relative z-10 text-center">
          <h3 className={`font-black text-white tracking-tight uppercase leading-none ${compact ? "text-[10px]" : "text-lg"}`}>
            {agent.name}
          </h3>
          <p className={`font-medium text-[#d4af37] tracking-widest uppercase mt-1.5 ${compact ? "text-[8px]" : "text-[10px]"}`}>
            {agent.role}
          </p>
        </div>
      </div>

      {/* Speaking Glow Effect */}
      {agent.speaking && (
        <div className="absolute inset-x-0 bottom-0 h-1 gold-gradient shadow-[0_-10px_30px_rgba(212,175,55,0.5)]" />
      )}
    </motion.div>
  );
}
