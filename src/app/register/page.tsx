"use client";

import { motion } from "framer-motion";
import { Brain, Mail, Lock, User, ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

export default function RegisterPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(false);

    try {
      const res = await fetch("/api/register", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ name, email, password }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.message || "Ocorreu um erro. Tente novamente.");
      }

      setSuccess(true);
      // Opcional: Redirecionar para login após 3 segundos
      setTimeout(() => {
        window.location.href = "/login";
      }, 3000);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden bg-[#030712]">
      {/* Background Animated Orbs */}
      <div className="absolute top-[-10%] right-[-10%] w-[40%] h-[40%] bg-[#b08d24]/10 rounded-full blur-[120px] animate-orb" />
      <div className="absolute bottom-[-10%] left-[-10%] w-[40%] h-[40%] bg-[#d4af37]/10 rounded-full blur-[120px] animate-orb" style={{ animationDelay: '-7s' }} />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[60%] h-[60%] bg-blue-500/5 rounded-full blur-[150px] pointer-events-none" />

      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
        className="relative w-full max-w-md z-10"
      >
        <div className="glass-card-premium p-10 border-white/5">
          {/* Logo Section */}
          <div className="flex flex-col items-center mb-10">
            <Link href="/" className="group relative">
              <div className="absolute -inset-4 bg-[#d4af37]/20 rounded-full blur-xl opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
              <div className="relative bg-gradient-to-br from-[#d4af37] to-[#b08d24] p-3 rounded-2xl gold-glow shadow-2xl">
                <img src="/logo-icon.svg" alt="Hive Mind" className="w-10 h-10 object-contain brightness-0 invert" />
              </div>
            </Link>
            <h2 className="mt-6 text-3xl font-bold tracking-tight text-white text-center">
              Hive Mind
            </h2>
          </div>

          <div className="space-y-2 mb-8 text-center">
            <h1 className="text-xl font-semibold text-white">Criar Nova Conta</h1>
            <p className="text-sm text-gray-500">Inicie sua jornada para a excelência</p>
          </div>

          {error && (
            <motion.div 
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-6 p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-500 text-sm text-center"
            >
              {error}
            </motion.div>
          )}

          {success && (
            <motion.div 
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="mb-6 p-4 rounded-xl bg-green-500/10 border border-green-500/20 text-green-500 text-sm text-center font-medium"
            >
              Conta criada com sucesso! Redirecionando...
            </motion.div>
          )}

          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-2">
              <label htmlFor="name" className="block text-xs font-medium uppercase tracking-wider text-gray-500 ml-1">
                Nome do Consultor
              </label>
              <div className="relative group">
                <User className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 group-focus-within:text-[#d4af37] transition-colors" />
                <input
                  id="name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Seu nome completo"
                  className="w-full pl-12 pr-4 py-4 rounded-xl bg-white/5 border border-white/10 focus:border-[#d4af37] focus:ring-1 focus:ring-[#d4af37] outline-none transition-all text-sm placeholder-gray-600"
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <label htmlFor="email" className="block text-xs font-medium uppercase tracking-wider text-gray-500 ml-1">
                E-mail Profissional
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

            <div className="space-y-2">
              <label htmlFor="password" className="block text-xs font-medium uppercase tracking-wider text-gray-500 ml-1">
                Senha de Acesso
              </label>
              <div className="relative group">
                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 group-focus-within:text-[#d4af37] transition-colors" />
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="No mínimo 8 caracteres"
                  className="w-full pl-12 pr-4 py-4 rounded-xl bg-white/5 border border-white/10 focus:border-[#d4af37] focus:ring-1 focus:ring-[#d4af37] outline-none transition-all text-sm placeholder-gray-600"
                  required
                  minLength={8}
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full relative group overflow-hidden bg-gradient-to-r from-[#b08d24] to-[#d4af37] p-[1px] rounded-xl transition-all duration-300 hover:shadow-[0_0_30px_rgba(212,175,55,0.3)] mt-2"
            >
              <div className="relative bg-[#030712] group-hover:bg-transparent rounded-[11px] py-4 transition-all duration-300 flex items-center justify-center gap-2">
                {loading ? (
                  <div className="w-5 h-5 border-2 border-[#d4af37]/30 border-t-[#d4af37] rounded-full animate-spin" />
                ) : (
                  <>
                    <span className="font-semibold text-white group-hover:text-[#030712] transition-colors">Inicializar Registro</span>
                    <ArrowRight className="w-4 h-4 text-[#d4af37] group-hover:text-[#030712] transition-colors" />
                  </>
                )}
              </div>
            </button>
          </form>

          <div className="mt-10 text-center">
            <p className="text-sm text-gray-500">
              Já faz parte da Hive?{" "}
              <Link
                href="/login"
                className="text-[#d4af37] hover:text-[#f0dfa0] font-bold transition-all decoration-[#d4af37]/20 underline-offset-4 hover:underline"
              >
                Entrar na Conta
              </Link>
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
