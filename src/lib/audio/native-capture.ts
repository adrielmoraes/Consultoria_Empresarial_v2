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
const CLIPPING_LIMIT = 0.985;
const ANALYSER_FFT_SIZE = 2048;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function amplitudeToDb(amplitude: number): number {
  if (!Number.isFinite(amplitude) || amplitude <= 0) {
    return -100;
  }
  return 20 * Math.log10(amplitude);
}

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

function computeRmsDb(samples: Float32Array): { rms: number; rmsDb: number; peak: number; peakDb: number; clippingRatio: number } {
  if (!samples.length) {
    return { rms: 0, rmsDb: -100, peak: 0, peakDb: -100, clippingRatio: 0 };
  }

  let sumSquares = 0;
  let peak = 0;
  let clipping = 0;

  for (let i = 0; i < samples.length; i++) {
    const abs = Math.abs(samples[i]);
    sumSquares += samples[i] * samples[i];
    if (abs > peak) peak = abs;
    if (abs >= CLIPPING_LIMIT) clipping++;
  }

  const rms = Math.sqrt(sumSquares / samples.length);
  return {
    rms,
    rmsDb: amplitudeToDb(rms),
    peak,
    peakDb: amplitudeToDb(peak),
    clippingRatio: clipping / samples.length,
  };
}

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

  const localTrack = new LocalAudioTrack(sourceTrack, captureOptions, true);

  const audioContext = new AudioContext({ latencyHint: "interactive", sampleRate: REQUESTED_SAMPLE_RATE });
  if (audioContext.state === "suspended") {
    await audioContext.resume().catch(() => undefined);
  }

  const sourceNode = audioContext.createMediaStreamSource(stream);
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = ANALYSER_FFT_SIZE;
  analyser.smoothingTimeConstant = 0.75;

  const destination = audioContext.createMediaStreamDestination();
  sourceNode.connect(analyser);
  analyser.connect(destination);

  const processedTrack = destination.stream.getAudioTracks()[0];
  if (!processedTrack) {
    throw new Error("Falha ao gerar a trilha processada do microfone.");
  }
  processedTrack.contentHint = "speech";

  const settings = sourceTrack.getSettings() as ExtendedMediaTrackSettings;
  const appliedSampleRate = audioContext.sampleRate || settings.sampleRate || REQUESTED_SAMPLE_RATE;

  emitLog(onLog, "info", `Captura nativa iniciada em ${appliedSampleRate}Hz.`);

  let frameHandle = 0;
  let destroyed = false;
  let lastLogAt = 0;
  let noiseFloorDb = -72;
  const buffer = new Float32Array(ANALYSER_FFT_SIZE);

  const tick = () => {
    if (destroyed) return;

    analyser.getFloatTimeDomainData(buffer);
    const { rms, rmsDb, peak, peakDb, clippingRatio } = computeRmsDb(buffer);

    const candidateNoiseFloor = rmsDb < -60 ? noiseFloorDb * 0.95 + rmsDb * 0.05 : noiseFloorDb;
    noiseFloorDb = Number.isFinite(candidateNoiseFloor) ? candidateNoiseFloor : -72;
    const snrDb = rmsDb - noiseFloorDb;
    const health: AudioDiagnosticsSnapshot["health"] =
      clippingRatio > 0.08 || rmsDb < -62 ? "critical" :
      snrDb < 12 || clippingRatio > 0.025 || rmsDb < -52 ? "warning" : "good";

    if (health !== "good" && Date.now() - lastLogAt > 5000) {
      lastLogAt = Date.now();
      emitLog(onLog, "warn", `Qualidade de entrada: ${health === "critical" ? "crítica" : "degradada"} (rms=${Math.round(rmsDb)}dB, snr=${Math.round(snrDb)}dB).`);
    }

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
      micLevel: clamp(rms / 0.2, 0, 1),
      rmsDb,
      peakDb,
      noiseFloorDb,
      snrDb,
      clippingRatio,
      voiceActive: rmsDb > -48 && snrDb > 10,
      health,
      updatedAt: Date.now(),
    });

    frameHandle = window.requestAnimationFrame(tick);
  };

  frameHandle = window.requestAnimationFrame(tick);

  const cleanup = () => {
    if (destroyed) return;
    destroyed = true;
    if (frameHandle) window.cancelAnimationFrame(frameHandle);
    localTrack.stop();
    sourceTrack?.stop();
    stream?.getTracks().forEach((t) => t.stop());
    sourceNode.disconnect();
    analyser.disconnect();
    destination.disconnect();
    void audioContext.close().catch(() => undefined);
    emitLog(onLog, "info", "Captura nativa encerrada.");
  };

  sourceTrack.addEventListener("ended", () => {
    emitLog(onLog, "error", "A captura do microfone foi encerrada pelo navegador.");
  });

  return { localTrack, sourceTrack, cleanup };
}