import { describe, expect, it } from "vitest";
import {
  buildAudioCaptureOptions,
  computeAudioFrameMetrics,
  createInitialVadState,
  nextVadState,
  resolveMicrophoneError,
} from "./vad-monitor";

function createSineWave({
  amplitude,
  sampleCount = 2048,
  cycles = 18,
}: {
  amplitude: number;
  sampleCount?: number;
  cycles?: number;
}) {
  return Float32Array.from({ length: sampleCount }, (_, index) => (
    Math.sin((Math.PI * 2 * cycles * index) / sampleCount) * amplitude
  ));
}

describe("vad-monitor", () => {
  it("monta constraints de captura em mono com 48kHz", () => {
    const options = buildAudioCaptureOptions("mic-123");

    expect(options.deviceId).toEqual({ exact: "mic-123" });
    expect(options.channelCount).toEqual({ ideal: 1, max: 1 });
    expect(options.sampleRate).toEqual({ ideal: 48_000 });
    expect(options.sampleSize).toEqual({ ideal: 16 });
    expect(options.echoCancellation).toEqual({ ideal: true });
    expect(options.noiseSuppression).toEqual({ ideal: true });
    expect(options.autoGainControl).toEqual({ ideal: false });
  });

  it("mede silêncio sem detecção de clipping", () => {
    const metrics = computeAudioFrameMetrics(new Float32Array(1024));

    expect(metrics.rms).toBe(0);
    expect(metrics.peak).toBe(0);
    expect(metrics.rmsDb).toBe(-100);
    expect(metrics.clippingRatio).toBe(0);
  });

  it("detecta fala com energia suficiente após ruído baixo", () => {
    let state = createInitialVadState();

    for (let index = 0; index < 30; index += 1) {
      state = nextVadState(state, computeAudioFrameMetrics(createSineWave({ amplitude: 0.002 })));
    }

    state = nextVadState(
      state,
      computeAudioFrameMetrics(createSineWave({ amplitude: 0.12 })),
    );

    expect(state.voiceActive).toBe(true);
    expect(state.snrDb).toBeGreaterThan(10);
    expect(state.recommendedGain).toBeGreaterThanOrEqual(0.85);
  });

  it("mantém hangover para evitar cortes nas sílabas finais", () => {
    let state = createInitialVadState();

    for (let index = 0; index < 20; index += 1) {
      state = nextVadState(
        state,
        computeAudioFrameMetrics(createSineWave({ amplitude: 0.11 })),
      );
    }

    expect(state.voiceActive).toBe(true);

    state = nextVadState(state, computeAudioFrameMetrics(new Float32Array(2048)));
    expect(state.voiceActive).toBe(true);

    for (let index = 0; index < 12; index += 1) {
      state = nextVadState(state, computeAudioFrameMetrics(new Float32Array(2048)));
    }

    expect(state.voiceActive).toBe(false);
  });

  it("converte erros conhecidos de microfone em mensagens operacionais", () => {
    expect(resolveMicrophoneError(new Error("falha genérica"))).toBe("falha genérica");
    expect(
      resolveMicrophoneError({}),
    ).toBe("Falha ao inicializar o microfone.");
  });
});
