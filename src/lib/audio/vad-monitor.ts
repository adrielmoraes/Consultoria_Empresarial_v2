import { LocalAudioTrack, type AudioCaptureOptions } from "livekit-client";

export type AudioLogLevel = "info" | "warn" | "error";

export type AudioRuntimeLog = {
  level: AudioLogLevel;
  message: string;
  timestamp: string;
};

export type AudioFrameMetrics = {
  rms: number;
  peak: number;
  rmsDb: number;
  peakDb: number;
  clippingRatio: number;
  zeroCrossingRate: number;
};

export type VadThresholds = {
  minVoiceDb: number;
  minPeak: number;
  activationSnrDb: number;
  holdSnrDb: number;
  hangoverFrames: number;
  noiseFloorAlpha: number;
  targetRms: number;
  minGain: number;
  maxGain: number;
  idleGain: number;
};

export type VadState = {
  voiceActive: boolean;
  hangover: number;
  noiseFloorDb: number;
  snrDb: number;
  recommendedGain: number;
  smoothedRms: number;
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

export type VoiceCapturePipeline = {
  localTrack: LocalAudioTrack;
  sourceTrack: MediaStreamTrack;
  processedTrack: MediaStreamTrack;
  setMuted: (muted: boolean) => Promise<void>;
  getSnapshot: () => AudioDiagnosticsSnapshot;
  cleanup: () => void;
};

type ExtendedMediaTrackSettings = MediaTrackSettings & {
  latency?: number;
  voiceIsolation?: boolean;
};

export const DEFAULT_VAD_THRESHOLDS: VadThresholds = {
  minVoiceDb: -48,
  minPeak: 0.018,
  activationSnrDb: 10,
  holdSnrDb: 6,
  hangoverFrames: 10,
  noiseFloorAlpha: 0.92,
  targetRms: 0.14,
  minGain: 0.85,
  maxGain: 2.8,
  idleGain: 0.72,
};

const REQUESTED_SAMPLE_RATE = 48_000;
const DEFAULT_SAMPLE_SIZE = 16;
const MIN_ANALYSER_LEVEL = 1e-4;
const CLIPPING_LIMIT = 0.985;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function amplitudeToDb(amplitude: number): number {
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

export function computeAudioFrameMetrics(samples: Float32Array): AudioFrameMetrics {
  if (!samples.length) {
    return {
      rms: 0,
      peak: 0,
      rmsDb: -100,
      peakDb: -100,
      clippingRatio: 0,
      zeroCrossingRate: 0,
    };
  }

  let sumSquares = 0;
  let peak = 0;
  let clipping = 0;
  let zeroCrossings = 0;

  for (let index = 0; index < samples.length; index += 1) {
    const current = samples[index];
    const absolute = Math.abs(current);
    sumSquares += current * current;
    if (absolute > peak) {
      peak = absolute;
    }
    if (absolute >= CLIPPING_LIMIT) {
      clipping += 1;
    }
    if (index > 0) {
      const previous = samples[index - 1];
      if (
        (previous >= 0 && current < 0) ||
        (previous < 0 && current >= 0)
      ) {
        zeroCrossings += 1;
      }
    }
  }

  const rms = Math.sqrt(sumSquares / samples.length);

  return {
    rms,
    peak,
    rmsDb: amplitudeToDb(rms),
    peakDb: amplitudeToDb(peak),
    clippingRatio: clipping / samples.length,
    zeroCrossingRate: zeroCrossings / samples.length,
  };
}

export function nextVadState(
  previous: VadState,
  metrics: AudioFrameMetrics,
  thresholds: VadThresholds = DEFAULT_VAD_THRESHOLDS,
): VadState {
  const smoothedRms =
    previous.smoothedRms === 0
      ? metrics.rms
      : previous.smoothedRms * 0.78 + metrics.rms * 0.22;

  const smoothedRmsDb = amplitudeToDb(smoothedRms);
  const candidateNoiseFloor = previous.voiceActive
    ? previous.noiseFloorDb
    : previous.noiseFloorDb * thresholds.noiseFloorAlpha +
      metrics.rmsDb * (1 - thresholds.noiseFloorAlpha);

  const noiseFloorDb = Number.isFinite(candidateNoiseFloor)
    ? candidateNoiseFloor
    : metrics.rmsDb;
  const snrDb = smoothedRmsDb - noiseFloorDb;

  const shouldActivate =
    smoothedRmsDb >= thresholds.minVoiceDb &&
    metrics.peak >= thresholds.minPeak &&
    snrDb >= thresholds.activationSnrDb;

  const shouldHold =
    smoothedRmsDb >= thresholds.minVoiceDb &&
    metrics.peak >= thresholds.minPeak * 0.72 &&
    snrDb >= thresholds.holdSnrDb;

  let voiceActive = previous.voiceActive;
  let hangover = previous.hangover;

  if (shouldActivate) {
    voiceActive = true;
    hangover = thresholds.hangoverFrames;
  } else if (voiceActive && shouldHold) {
    hangover = thresholds.hangoverFrames;
  } else if (voiceActive && hangover > 0) {
    hangover -= 1;
  } else {
    voiceActive = false;
    hangover = 0;
  }

  const baseGain = thresholds.targetRms / Math.max(smoothedRms, MIN_ANALYSER_LEVEL);
  const recommendedGain = clamp(
    voiceActive ? baseGain : Math.min(baseGain, thresholds.idleGain),
    thresholds.minGain,
    thresholds.maxGain,
  );

  return {
    voiceActive,
    hangover,
    noiseFloorDb,
    snrDb,
    recommendedGain,
    smoothedRms,
  };
}

export function createInitialVadState(): VadState {
  return {
    voiceActive: false,
    hangover: 0,
    noiseFloorDb: -72,
    snrDb: 0,
    recommendedGain: 1,
    smoothedRms: 0,
  };
}

export function getAudioHealth(snapshot: Pick<AudioDiagnosticsSnapshot, "snrDb" | "clippingRatio" | "rmsDb">): AudioDiagnosticsSnapshot["health"] {
  if (snapshot.clippingRatio > 0.08 || snapshot.rmsDb < -62) {
    return "critical";
  }
  if (snapshot.snrDb < 12 || snapshot.clippingRatio > 0.025 || snapshot.rmsDb < -52) {
    return "warning";
  }
  return "good";
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

async function queryMicrophonePermission(): Promise<PermissionState | "unsupported" | "unknown"> {
  if (typeof navigator === "undefined" || !("permissions" in navigator)) {
    return "unsupported";
  }

  try {
    const status = await navigator.permissions.query({
      name: "microphone" as PermissionName,
    });
    return status.state;
  } catch {
    return "unknown";
  }
}

export async function inspectAudioInputState(
  preferredDeviceId?: string | null,
): Promise<AudioInputProbe> {
  const permissionState = await queryMicrophonePermission();
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

type VoiceCapturePipelineOptions = {
  deviceId?: string | null;
  thresholds?: VadThresholds;
  onLog?: (log: AudioRuntimeLog) => void;
  onDiagnostics?: (snapshot: AudioDiagnosticsSnapshot) => void;
};

function emitLog(
  onLog: VoiceCapturePipelineOptions["onLog"],
  level: AudioLogLevel,
  message: string,
) {
  onLog?.({
    level,
    message,
    timestamp: createTimestamp(),
  });
}

export async function createVoiceCapturePipeline(
  options: VoiceCapturePipelineOptions = {},
): Promise<VoiceCapturePipeline> {
  const thresholds = options.thresholds ?? DEFAULT_VAD_THRESHOLDS;
  const probe = await inspectAudioInputState(options.deviceId);
  const captureOptions = buildAudioCaptureOptions(
    options.deviceId ?? probe.selectedDeviceId ?? undefined,
  );
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: captureOptions,
    video: false,
  });

  const sourceTrack = stream.getAudioTracks()[0];
  if (!sourceTrack) {
    throw new Error("Nenhuma trilha de áudio foi criada pelo navegador.");
  }

  const audioContext = new AudioContext({
    latencyHint: "interactive",
    sampleRate: REQUESTED_SAMPLE_RATE,
  });

  if (audioContext.state === "suspended") {
    await audioContext.resume().catch(() => undefined);
  }

  const sourceNode = audioContext.createMediaStreamSource(stream);
  const highPass = audioContext.createBiquadFilter();
  highPass.type = "highpass";
  highPass.frequency.value = 80;
  highPass.Q.value = 0.7;

  const lowPass = audioContext.createBiquadFilter();
  lowPass.type = "lowpass";
  lowPass.frequency.value = 7600;
  lowPass.Q.value = 0.7;

  const compressor = audioContext.createDynamicsCompressor();
  compressor.threshold.value = -24;
  compressor.knee.value = 18;
  compressor.ratio.value = 3.5;
  compressor.attack.value = 0.004;
  compressor.release.value = 0.14;

  const gainNode = audioContext.createGain();
  gainNode.gain.value = 1;

  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 2048;
  analyser.smoothingTimeConstant = 0.72;

  const destination = audioContext.createMediaStreamDestination();

  sourceNode.connect(highPass);
  highPass.connect(lowPass);
  lowPass.connect(compressor);
  compressor.connect(gainNode);
  gainNode.connect(analyser);
  gainNode.connect(destination);

  const processedTrack = destination.stream.getAudioTracks()[0];
  if (!processedTrack) {
    throw new Error("Falha ao gerar a trilha processada do microfone.");
  }

  processedTrack.contentHint = "speech";

  const localTrack = new LocalAudioTrack(processedTrack, captureOptions, true);
  let frameHandle = 0;
  let destroyed = false;
  let vadState = createInitialVadState();
  let lastVoiceState = false;
  let lastLogAt = 0;
  const buffer = new Float32Array(analyser.fftSize);
  const sourceSettings = sourceTrack.getSettings() as ExtendedMediaTrackSettings;
  const appliedSampleRate = audioContext.sampleRate || sourceSettings.sampleRate || REQUESTED_SAMPLE_RATE;
  const diagnostics: AudioDiagnosticsSnapshot = {
    permissionState: probe.permissionState,
    requestedSampleRate: REQUESTED_SAMPLE_RATE,
    appliedSampleRate,
    sampleSize: sourceSettings.sampleSize ?? DEFAULT_SAMPLE_SIZE,
    channelCount: sourceSettings.channelCount ?? 1,
    latencyMs:
      typeof sourceSettings.latency === "number"
        ? Math.round(sourceSettings.latency * 1000)
        : null,
    echoCancellation:
      typeof sourceSettings.echoCancellation === "boolean"
        ? sourceSettings.echoCancellation
        : null,
    noiseSuppression:
      typeof sourceSettings.noiseSuppression === "boolean"
        ? sourceSettings.noiseSuppression
        : null,
    autoGainControl:
      typeof sourceSettings.autoGainControl === "boolean"
        ? sourceSettings.autoGainControl
        : null,
    voiceIsolation:
      typeof sourceSettings.voiceIsolation === "boolean"
        ? sourceSettings.voiceIsolation
        : null,
    selectedDeviceId: sourceSettings.deviceId ?? probe.selectedDeviceId ?? null,
    selectedDeviceLabel: probe.selectedDeviceLabel,
    availableDevices: probe.devices.length,
    micLevel: 0,
    rmsDb: -100,
    peakDb: -100,
    noiseFloorDb: vadState.noiseFloorDb,
    snrDb: vadState.snrDb,
    clippingRatio: 0,
    voiceActive: false,
    health: "warning",
    updatedAt: Date.now(),
  };

  emitLog(
    options.onLog,
    "info",
    `Microfone inicializado em ${appliedSampleRate}Hz${diagnostics.channelCount ? ` / ${diagnostics.channelCount} canal` : ""}.`,
  );

  const tick = () => {
    if (destroyed) {
      return;
    }

    analyser.getFloatTimeDomainData(buffer);
    const metrics = computeAudioFrameMetrics(buffer);
    vadState = nextVadState(vadState, metrics, thresholds);

    gainNode.gain.setTargetAtTime(
      vadState.recommendedGain,
      audioContext.currentTime,
      vadState.voiceActive ? 0.02 : 0.08,
    );

    diagnostics.micLevel = clamp(metrics.rms / 0.2, 0, 1);
    diagnostics.rmsDb = metrics.rmsDb;
    diagnostics.peakDb = metrics.peakDb;
    diagnostics.noiseFloorDb = vadState.noiseFloorDb;
    diagnostics.snrDb = vadState.snrDb;
    diagnostics.clippingRatio = metrics.clippingRatio;
    diagnostics.voiceActive = vadState.voiceActive;
    diagnostics.health = getAudioHealth(diagnostics);
    diagnostics.updatedAt = Date.now();

    if (vadState.voiceActive !== lastVoiceState) {
      lastVoiceState = vadState.voiceActive;
      emitLog(
        options.onLog,
        vadState.voiceActive ? "info" : "warn",
        vadState.voiceActive
          ? `Fala detectada com SNR de ${Math.round(vadState.snrDb)}dB.`
          : "VAD voltou para silêncio monitorado.",
      );
    }

    if (
      diagnostics.health !== "good" &&
      Date.now() - lastLogAt > 4000
    ) {
      lastLogAt = Date.now();
      const detail =
        diagnostics.clippingRatio > 0.025
          ? "clipping detectado"
          : diagnostics.snrDb < 12
            ? `SNR baixo (${Math.round(diagnostics.snrDb)}dB)`
            : "sinal muito fraco";
      emitLog(options.onLog, "warn", `Qualidade de entrada degradada: ${detail}.`);
    }

    options.onDiagnostics?.({ ...diagnostics });
    frameHandle = window.requestAnimationFrame(tick);
  };

  frameHandle = window.requestAnimationFrame(tick);

  const cleanup = () => {
    if (destroyed) {
      return;
    }
    destroyed = true;
    if (frameHandle) {
      window.cancelAnimationFrame(frameHandle);
    }
    localTrack.stop();
    processedTrack.stop();
    sourceTrack.stop();
    stream.getTracks().forEach((track) => track.stop());
    sourceNode.disconnect();
    highPass.disconnect();
    lowPass.disconnect();
    compressor.disconnect();
    gainNode.disconnect();
    analyser.disconnect();
    destination.disconnect();
    void audioContext.close().catch(() => undefined);
  };

  sourceTrack.addEventListener("ended", () => {
    emitLog(options.onLog, "error", "A captura do microfone foi encerrada pelo navegador.");
  });

  return {
    localTrack,
    sourceTrack,
    processedTrack,
    setMuted: async (muted: boolean) => {
      sourceTrack.enabled = !muted;
      processedTrack.enabled = !muted;
      if (muted) {
        await localTrack.mute();
        emitLog(options.onLog, "info", "Microfone silenciado.");
      } else {
        await audioContext.resume().catch(() => undefined);
        await localTrack.unmute();
        emitLog(options.onLog, "info", "Microfone reativado.");
      }
    },
    getSnapshot: () => ({ ...diagnostics }),
    cleanup,
  };
}
