"use client";

import { useState, useRef, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Mic, MicOff, Users, Loader2, ArrowRight } from "lucide-react";
import Image from "next/image";

export default function JoinLobbyPage() {
  const params = useParams();
  const router = useRouter();
  const roomId = params.roomId as string;

  const [guestName, setGuestName] = useState("");
  const [micTested, setMicTested] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [testingMic, setTestingMic] = useState(false);
  const [joining, setJoining] = useState(false);
  const streamRef = useRef<MediaStream | null>(null);

  // Cleanup mic stream on unmount
  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const testMicrophone = async () => {
    setTestingMic(true);
    setMicError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      setMicTested(true);
      // Stop after 2 seconds
      setTimeout(() => {
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }, 2000);
    } catch {
      setMicError(
        "Não foi possível acessar o microfone. Verifique as permissões do navegador."
      );
    } finally {
      setTestingMic(false);
    }
  };

  const handleJoin = async () => {
    if (!guestName.trim() || !micTested) return;
    setJoining(true);

    // Redireciona para a sala de guest com o nome e roomId via query params
    const searchParams = new URLSearchParams({
      name: guestName.trim(),
      room: `mentoria-${roomId}`,
    });
    router.push(`/mentorship/guest/${roomId}?${searchParams.toString()}`);
  };

  return (
    <div className="min-h-screen bg-[#030712] flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-md"
      >
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-[#0a0a0f] border border-[#d4af37]/30 mb-4 p-1.5">
            <Image
              src="/logo-icon.svg?v=2"
              alt="Hive Mind"
              width={48}
              height={48}
              className="w-full h-full object-contain"
              style={{
                filter:
                  "brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)",
              }}
            />
          </div>
          <h1 className="text-2xl font-bold text-white mb-1">Hive Mind</h1>
          <p className="text-sm text-gray-400">
            Você foi convidado para uma sessão de mentoria
          </p>
        </div>

        {/* Card */}
        <div className="bg-gray-900/80 border border-white/10 rounded-2xl p-6 backdrop-blur-xl shadow-2xl space-y-6">
          {/* Nome */}
          <div>
            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Seu Nome e Cargo
            </label>
            <input
              type="text"
              value={guestName}
              onChange={(e) => setGuestName(e.target.value)}
              placeholder="Ex: Lucas — Sócio Financeiro"
              className="w-full px-4 py-3 rounded-xl bg-black/40 border border-white/10 text-white placeholder-gray-600 text-sm focus:outline-none focus:border-[#d4af37]/50 focus:ring-1 focus:ring-[#d4af37]/20 transition-all"
              maxLength={50}
            />
          </div>

          {/* Teste de Microfone */}
          <div>
            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Teste de Microfone
            </label>
            <button
              onClick={testMicrophone}
              disabled={testingMic}
              className={`w-full flex items-center justify-center gap-3 px-4 py-3 rounded-xl border text-sm font-medium transition-all ${
                micTested
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                  : micError
                  ? "border-red-500/30 bg-red-500/10 text-red-400"
                  : "border-white/10 bg-white/5 text-gray-300 hover:bg-white/10 hover:border-white/20"
              }`}
            >
              {testingMic ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Testando...
                </>
              ) : micTested ? (
                <>
                  <Mic className="w-4 h-4" />
                  Microfone OK ✓
                </>
              ) : micError ? (
                <>
                  <MicOff className="w-4 h-4" />
                  Erro — Clique para tentar novamente
                </>
              ) : (
                <>
                  <Mic className="w-4 h-4" />
                  Testar Microfone
                </>
              )}
            </button>
            {micError && (
              <p className="text-xs text-red-400 mt-1.5">{micError}</p>
            )}
          </div>

          {/* Info da Sala */}
          <div className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-[#d4af37]/5 border border-[#d4af37]/20">
            <Users className="w-4 h-4 text-[#d4af37] shrink-0" />
            <p className="text-xs text-[#d4af37]/80">
              Você entrará como <span className="font-semibold">Participante</span>. 
              Poderá ouvir e falar com os especialistas, mas não terá controle administrativo da mentoria.
            </p>
          </div>

          {/* Botão Entrar */}
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={handleJoin}
            disabled={!guestName.trim() || !micTested || joining}
            className="w-full flex items-center justify-center gap-2 px-4 py-3.5 rounded-xl bg-[#d4af37] hover:bg-[#b08d24] disabled:bg-gray-800 disabled:text-gray-600 text-[#030712] font-bold text-sm transition-all shadow-lg shadow-[#d4af37]/20 disabled:shadow-none"
          >
            {joining ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Entrando...
              </>
            ) : (
              <>
                Entrar na Reunião
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </motion.button>
        </div>

        <p className="text-center text-[10px] text-gray-600 mt-6">
          Powered by Hive Mind · Mentoria Empresarial Inteligente
        </p>
      </motion.div>
    </div>
  );
}
