"use client";

import { motion } from "framer-motion";
import { Mail, ArrowLeft, ArrowRight, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    // Como ainda não temos um serviço de e-mail (Resend/Nodemailer) configurado,
    // simulamos a chamada para manter o fluxo de UI fluido.
    setTimeout(() => {
      setLoading(false);
      setSuccess(true);
    }, 1500);
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden bg-[#030712]">
      {/* Background Animated Orbs */}
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-[#d4af37]/10 rounded-full blur-[120px] animate-orb" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-[#b08d24]/10 rounded-full blur-[120px] animate-orb" style={{ animationDelay: '-5s' }} />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[60%] h-[60%] bg-blue-500/5 rounded-full blur-[150px] pointer-events-none" />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
        className="relative w-full max-w-md z-10"
      >
        <div className="glass-card-premium p-10 border-white/5">
          {/* Logo Section */}
          <div className="flex flex-col items-center mb-10">
            <Link href="/" className="group relative">
              <div className="absolute -inset-4 bg-[#d4af37]/20 rounded-full blur-xl opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
              <div className="relative w-20 h-20 p-2 rounded-2xl bg-[#0a0a0f] border border-[#d4af37]/30 shadow-[0_0_25px_rgba(212,175,55,0.15)] flex items-center justify-center group-hover:border-[#d4af37]/60 transition-all duration-300">
                <img src="/logo-icon.svg?v=2" alt="Hive Mind" className="w-full h-full object-contain" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
              </div>
            </Link>
            <h2 className="mt-6 text-3xl font-bold tracking-tight text-white">
              Recuperar Acesso
            </h2>
            <p className="mt-2 text-sm text-gray-400 text-center">
              Informe seu e-mail para receber as instruções de redefinição.
            </p>
          </div>

          {success ? (
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="text-center space-y-6"
            >
              <div className="w-16 h-16 bg-[#d4af37]/10 rounded-full flex items-center justify-center mx-auto mb-4 border border-[#d4af37]/20">
                <CheckCircle2 className="w-8 h-8 text-[#d4af37]" />
              </div>
              <h3 className="text-xl font-semibold text-white">E-mail Enviado!</h3>
              <p className="text-sm text-gray-400">
                Se o e-mail <strong>{email}</strong> estiver cadastrado em nossa base, você receberá um link para redefinir sua senha em instantes.
              </p>
              <Link
                href="/login"
                className="w-full inline-flex items-center justify-center gap-2 py-4 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 text-white font-medium transition-all"
              >
                <ArrowLeft className="w-4 h-4" />
                Voltar para o Login
              </Link>
            </motion.div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-2">
                <label htmlFor="email" className="block text-xs font-medium uppercase tracking-wider text-gray-500 ml-1">
                  E-mail Corporativo
                </label>
                <div className="relative group">
                  <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 group-focus-within:text-[#d4af37] transition-colors" />
                  <input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="exemplo@empresa.com"
                    className="w-full pl-12 pr-4 py-4 rounded-xl bg-white/5 border border-white/10 focus:border-[#d4af37] focus:ring-1 focus:ring-[#d4af37] outline-none transition-all text-sm placeholder-gray-600"
                    required
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={loading || !email}
                className="w-full relative group overflow-hidden bg-gradient-to-r from-[#b08d24] to-[#d4af37] p-[1px] rounded-xl transition-all duration-300 hover:shadow-[0_0_30px_rgba(212,175,55,0.3)] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <div className="relative bg-[#030712] group-hover:bg-transparent rounded-[11px] py-4 transition-all duration-300 flex items-center justify-center gap-2">
                  {loading ? (
                    <div className="w-5 h-5 border-2 border-[#d4af37]/30 border-t-[#d4af37] rounded-full animate-spin" />
                  ) : (
                    <>
                      <span className="font-semibold text-white group-hover:text-[#030712] transition-colors">Enviar Link</span>
                      <ArrowRight className="w-4 h-4 text-[#d4af37] group-hover:text-[#030712] transition-colors" />
                    </>
                  )}
                </div>
              </button>

              <div className="text-center pt-2">
                <Link
                  href="/login"
                  className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-[#d4af37] transition-colors"
                >
                  <ArrowLeft className="w-4 h-4" />
                  Voltar para o Login
                </Link>
              </div>
            </form>
          )}
        </div>
      </motion.div>
    </div>
  );
}
