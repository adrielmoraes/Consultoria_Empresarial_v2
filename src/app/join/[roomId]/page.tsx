"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { AlertCircle, ArrowRight, Loader2, User, Video } from "lucide-react";
import Link from "next/link";

export default function JoinRoomRedirect() {
  const router = useRouter();
  const { roomId } = useParams();
  const inviteId = useMemo(
    () => (Array.isArray(roomId) ? roomId[0] : roomId),
    [roomId]
  );
  const [guestName, setGuestName] = useState("");
  const [activeRoomName, setActiveRoomName] = useState("");
  const [status, setStatus] = useState<
    "loading" | "ready" | "invalid" | "submitting"
  >("loading");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    if (!inviteId) {
      setStatus("invalid");
      setErrorMessage("Link de convite invalido.");
      return;
    }

    const currentInviteId = inviteId;
    const controller = new AbortController();

    async function resolveActiveRoom() {
      try {
        setStatus("loading");
        setErrorMessage("");

        const response = await fetch(
          `/api/livekit/guest-room/${encodeURIComponent(currentInviteId)}`,
          { signal: controller.signal, cache: "no-store" }
        );

        const data = (await response.json().catch(() => null)) as
          | { roomName?: string; error?: string }
          | null;

        if (!response.ok || !data?.roomName) {
          setStatus("invalid");
          setErrorMessage(
            data?.error ||
              "Nenhuma mentoria ativa foi encontrada para este convite."
          );
          return;
        }

        setActiveRoomName(data.roomName);
        setStatus("ready");
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }

        console.error("Erro ao resolver sala do convite:", error);
        setStatus("invalid");
        setErrorMessage("Nao foi possivel validar este link de convite.");
      }
    }

    void resolveActiveRoom();

    return () => controller.abort();
  }, [inviteId]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmedName = guestName.trim();
    if (!trimmedName || !inviteId || !activeRoomName) {
      return;
    }

    setStatus("submitting");
    const query = new URLSearchParams({
      name: trimmedName,
      room: activeRoomName,
    });
    router.push(`/mentorship/guest/${inviteId}?${query.toString()}`);
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden bg-[#030712]">
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-[#d4af37]/10 rounded-full blur-[120px] animate-orb" />
      <div
        className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-[#b08d24]/10 rounded-full blur-[120px] animate-orb"
        style={{ animationDelay: "-5s" }}
      />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[60%] h-[60%] bg-blue-500/5 rounded-full blur-[150px] pointer-events-none" />

      <div className="relative w-full max-w-md z-10">
        <div className="glass-card-premium p-10 border-white/5">
          <div className="flex flex-col items-center mb-10 text-center">
            <Link href="/" className="group relative">
              <div className="absolute -inset-4 bg-[#d4af37]/20 rounded-full blur-xl opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
              <div className="relative w-20 h-20 p-2 rounded-2xl bg-[#0a0a0f] border border-[#d4af37]/30 shadow-[0_0_25px_rgba(212,175,55,0.15)] flex items-center justify-center group-hover:border-[#d4af37]/60 transition-all duration-300">
                <img
                  src="/logo-icon.svg?v=2"
                  alt="Hive Mind"
                  className="w-full h-full object-contain"
                  style={{
                    filter:
                      "brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)",
                  }}
                />
              </div>
            </Link>
            <h2 className="mt-6 text-3xl font-bold tracking-tight text-white">
              Entrar na reuniao
            </h2>
            <p className="mt-2 text-sm text-gray-400">
              Informe seu nome para acessar a mentoria como convidado.
            </p>
          </div>

          {status === "loading" ? (
            <div className="flex items-center justify-center gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-5 text-sm text-gray-300">
              <Loader2 className="w-5 h-5 animate-spin text-[#d4af37]" />
              Validando link de convite...
            </div>
          ) : status === "invalid" ? (
            <div className="rounded-2xl border border-red-500/20 bg-red-500/10 p-5 text-left">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 rounded-full bg-red-500/15 p-2">
                  <AlertCircle className="w-4 h-4 text-red-300" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">
                    Convite indisponivel
                  </h3>
                  <p className="mt-1 text-sm text-red-100/80">
                    {errorMessage}
                  </p>
                  <p className="mt-2 text-xs text-gray-400">
                    Peça ao anfitriao para abrir a reuniao novamente e gerar um
                    novo convite, se necessario.
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-2">
                <label
                  htmlFor="guestName"
                  className="block text-xs font-medium uppercase tracking-wider text-gray-500 ml-1"
                >
                  Seu nome
                </label>
                <div className="relative group">
                  <User className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 group-focus-within:text-[#d4af37] transition-colors" />
                  <input
                    id="guestName"
                    type="text"
                    value={guestName}
                    onChange={(event) => setGuestName(event.target.value)}
                    placeholder="Ex: Maria"
                    className="w-full pl-12 pr-4 py-4 rounded-xl bg-white/5 border border-white/10 focus:border-[#d4af37] focus:ring-1 focus:ring-[#d4af37] outline-none transition-all text-sm placeholder-gray-600"
                    required
                    autoFocus
                    maxLength={60}
                  />
                </div>
              </div>

              <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-xs text-emerald-100/90">
                O acesso sera feito como convidado, sem necessidade de login.
              </div>

              <button
                type="submit"
                disabled={status === "submitting" || !guestName.trim()}
                className="w-full relative group overflow-hidden bg-gradient-to-r from-[#b08d24] to-[#d4af37] p-[1px] rounded-xl transition-all duration-300 hover:shadow-[0_0_30px_rgba(212,175,55,0.3)] disabled:opacity-50"
              >
                <div className="relative bg-[#030712] group-hover:bg-transparent rounded-[11px] py-4 transition-all duration-300 flex items-center justify-center gap-2">
                  {status === "submitting" ? (
                    <div className="w-5 h-5 border-2 border-[#d4af37]/30 border-t-[#d4af37] rounded-full animate-spin" />
                  ) : (
                    <>
                      <span className="font-semibold text-white group-hover:text-[#030712] transition-colors uppercase tracking-widest">
                        Entrar na Reuniao
                      </span>
                      <Video className="w-4 h-4 text-[#d4af37] group-hover:text-[#030712] transition-colors" />
                    </>
                  )}
                </div>
              </button>
            </form>
          )}

          <div className="mt-10 text-center">
            <Link
              href="/"
              className="text-xs text-gray-500 hover:text-[#d4af37] transition-colors flex items-center justify-center gap-2"
            >
              <ArrowRight className="w-3 h-3 rotate-180" />
              Voltar ao Inicio
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
