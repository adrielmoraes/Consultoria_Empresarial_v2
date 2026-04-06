import { LocalAudioTrack, type AudioCaptureOptions } from "livekit-client";

export type AudioLogLevel = "info" | "warn" | "error";

export type AudioRuntimeLog = {
  level: AudioLogLevel;
  message: string;
  timestamp: string;
};

export type AudioDiagnosticsSnapshot = {
  permissionState: PermissionState | "unsupported" | "unknown";
  requestedSampleRate: number;
  appliedSampleRate: number;
  sampleSize: number | null;
  channelCount: number | null;
  latencyMs: number | null;
  echoCancellation: boolean | null;
  noiseSuppression: boolean | null;
  autoGainControl: boolean | null;
  voiceIsolation: boolean | null;
  selectedDeviceId: string | null;
  selectedDeviceLabel: string | null;
  availableDevices: number;
  micLevel: number;
  rmsDb: number;
  peakDb: number;
  noiseFloorDb: number;
  snrDb: number;
  clippingRatio: number;
  voiceActive: boolean;
  health: "good" | "warning" | "critical";
  updatedAt: number;
};

export type AudioInputProbe = {
  permissionState: PermissionState | "unsupported" | "unknown";
  devices: MediaDeviceInfo[];
  selectedDeviceLabel: string | null;
  selectedDeviceId: string | null;
};

export type NativeAudioCapture = {
  localTrack: LocalAudioTrack;
  sourceTrack: MediaStreamTrack;
  cleanup: () => void;
};

const REQUESTED_SAMPLE_RATE = 48_000;
const DEFAULT_SAMPLE_SIZE = 16;

export function buildAudioCaptureOptions(deviceId?: string): AudioCaptureOptions {
  return {
    deviceId: deviceId ? { exact: deviceId } : undefined,
    channelCount: { ideal: 1, max: 1 },
    sampleRate: { ideal: REQUESTED_SAMPLE_RATE },
    sampleSize: { ideal: DEFAULT_SAMPLE_SIZE },
    latency: { ideal: 0.02, max: 0.08 },
    echoCancellation: { ideal: true },
    noiseSuppression: { ideal: true },
    voiceIsolation: { ideal: true },
    autoGainControl: { ideal: false },
  };
}

export async function inspectAudioInputState(
  preferredDeviceId?: string | null,
): Promise<AudioInputProbe> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) {
    return {
      permissionState: "unsupported",
      devices: [],
      selectedDeviceLabel: null,
      selectedDeviceId: null,
    };
  }

  let permissionState: PermissionState | "unsupported" | "unknown" = "unknown";
  try {
    const status = await navigator.permissions.query({ name: "microphone" as PermissionName });
    permissionState = status.state;
  } catch {
    permissionState = "unknown";
  }

  const devices = await navigator.mediaDevices.enumerateDevices();
  const audioInputs = devices.filter((device) => device.kind === "audioinput");
  const selectedDevice =
    audioInputs.find((device) => device.deviceId === preferredDeviceId) ??
    audioInputs[0] ??
    null;

  return {
    permissionState,
    devices: audioInputs,
    selectedDeviceId: selectedDevice?.deviceId ?? null,
    selectedDeviceLabel: selectedDevice?.label || null,
  };
}

export function resolveMicrophoneError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      return "Permissão de microfone negada no navegador.";
    }
    if (error.name === "NotFoundError" || error.name === "DevicesNotFoundError") {
      return "Nenhum dispositivo de entrada de áudio foi encontrado.";
    }
    if (error.name === "NotReadableError" || error.name === "TrackStartError") {
      return "O microfone está em uso por outro aplicativo ou indisponível.";
    }
    if (error.name === "OverconstrainedError") {
      return "O navegador não conseguiu aplicar a configuração solicitada do microfone.";
    }
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Falha ao inicializar o microfone.";
}

function createTimestamp(): string {
  return new Date().toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

type NativeAudioCaptureOptions = {
  deviceId?: string | null;
  onLog?: (log: { level: AudioLogLevel; message: string; timestamp: string }) => void;
  onDiagnostics?: (snapshot: AudioDiagnosticsSnapshot) => void;
};

function emitLog(
  onLog: NativeAudioCaptureOptions["onLog"],
  level: AudioLogLevel,
  message: string,
) {
  onLog?.({
    level,
    message,
    timestamp: createTimestamp(),
  });
}

type ExtendedMediaTrackSettings = MediaTrackSettings & {
  latency?: number;
  voiceIsolation?: boolean;
};

export async function createNativeAudioCapture(
  options: NativeAudioCaptureOptions = {},
): Promise<NativeAudioCapture> {
  const { deviceId, onLog, onDiagnostics } = options;

  const captureOptions = buildAudioCaptureOptions(deviceId ?? undefined);

  let stream: MediaStream | null = null;
  let sourceTrack: MediaStreamTrack | null = null;

  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: captureOptions, video: false });
    sourceTrack = stream.getAudioTracks()[0];
    if (!sourceTrack) {
      throw new Error("Nenhuma trilha de áudio foi criada pelo navegador.");
    }
  } catch (err) {
    throw new Error(resolveMicrophoneError(err));
  }

  sourceTrack.contentHint = "speech";

  const settings = sourceTrack.getSettings() as ExtendedMediaTrackSettings;
  const appliedSampleRate = settings.sampleRate || REQUESTED_SAMPLE_RATE;
  const localTrack = new LocalAudioTrack(sourceTrack, captureOptions, true);

  emitLog(onLog, "info", `Captura nativa iniciada em ${appliedSampleRate}Hz.`);
  onDiagnostics?.({
    permissionState: "granted",
    requestedSampleRate: REQUESTED_SAMPLE_RATE,
    appliedSampleRate,
    sampleSize: settings.sampleSize ?? DEFAULT_SAMPLE_SIZE,
    channelCount: settings.channelCount ?? 1,
    latencyMs: typeof settings.latency === "number" ? Math.round(settings.latency * 1000) : null,
    echoCancellation: typeof settings.echoCancellation === "boolean" ? settings.echoCancellation : null,
    noiseSuppression: typeof settings.noiseSuppression === "boolean" ? settings.noiseSuppression : null,
    autoGainControl: typeof settings.autoGainControl === "boolean" ? settings.autoGainControl : null,
    voiceIsolation: typeof settings.voiceIsolation === "boolean" ? settings.voiceIsolation : null,
    selectedDeviceId: settings.deviceId ?? null,
    selectedDeviceLabel: null,
    availableDevices: 0,
    micLevel: 0,
    rmsDb: -100,
    peakDb: -100,
    noiseFloorDb: -72,
    snrDb: 0,
    clippingRatio: 0,
    voiceActive: false,
    health: "good",
    updatedAt: Date.now(),
  });

  const cleanup = () => {
    localTrack.stop();
    sourceTrack.stop();
    stream.getTracks().forEach((track) => track.stop());
    emitLog(onLog, "info", "Captura nativa encerrada.");
  };

  sourceTrack.addEventListener("ended", () => {
    emitLog(onLog, "error", "A captura do microfone foi encerrada pelo navegador.");
  });

  return { localTrack, sourceTrack, cleanup };
}
