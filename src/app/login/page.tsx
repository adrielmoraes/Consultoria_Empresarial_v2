"use client";

import { motion } from "framer-motion";
import { Brain, Mail, Lock, ArrowRight } from "lucide-react";
import Link from "next/link";
import { signIn } from "next-auth/react";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const res = await signIn("credentials", {
        redirect: false,
        email,
        password,
      });

      if (res?.error) {
        throw new Error(
          res.error === "CredentialsSignin"
            ? "E-mail ou senha incorretos."
            : res.error
        );
      }

      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
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
              <div className="relative w-16 h-16 rounded-2xl bg-[#0a0a0f] border border-[#d4af37]/30 shadow-[0_0_25px_rgba(212,175,55,0.15)] flex items-center justify-center group-hover:border-[#d4af37]/60 transition-all duration-300">
                <img src="/logo-icon.svg" alt="Hive Mind" className="w-10 h-10 object-contain" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
              </div>
            </Link>
            <h2 className="mt-6 text-3xl font-bold tracking-tight text-white">
              Hive Mind
            </h2>
            <p className="mt-2 text-sm text-gray-400">
              Gestão Inteligente & Consultoria de Elite
            </p>
          </div>

          <div className="space-y-2 mb-8 text-center">
            <h1 className="text-xl font-semibold text-white">Bem-vindo de volta</h1>
            <p className="text-sm text-gray-500">Acesse sua sala de comando</p>
          </div>

          {error && (
            <motion.div 
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="mb-6 p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-500 text-sm text-center"
            >
              {error}
            </motion.div>
          )}

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

            <div className="space-y-2">
              <div className="flex items-center justify-between ml-1">
                <label htmlFor="password" className="block text-xs font-medium uppercase tracking-wider text-gray-500">
                  Senha
                </label>
                <Link href="/forgot-password" className="text-xs text-[#d4af37] hover:text-[#f0dfa0] transition-colors font-medium">
                  Recuperar acesso?
                </Link>
              </div>
              <div className="relative group">
                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 group-focus-within:text-[#d4af37] transition-colors" />
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full pl-12 pr-4 py-4 rounded-xl bg-white/5 border border-white/10 focus:border-[#d4af37] focus:ring-1 focus:ring-[#d4af37] outline-none transition-all text-sm placeholder-gray-600"
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full relative group overflow-hidden bg-gradient-to-r from-[#b08d24] to-[#d4af37] p-[1px] rounded-xl transition-all duration-300 hover:shadow-[0_0_30px_rgba(212,175,55,0.3)]"
            >
              <div className="relative bg-[#030712] group-hover:bg-transparent rounded-[11px] py-4 transition-all duration-300 flex items-center justify-center gap-2">
                {loading ? (
                  <div className="w-5 h-5 border-2 border-[#d4af37]/30 border-t-[#d4af37] rounded-full animate-spin" />
                ) : (
                  <>
                    <span className="font-semibold text-white group-hover:text-[#030712] transition-colors">Acessar Plataforma</span>
                    <ArrowRight className="w-4 h-4 text-[#d4af37] group-hover:text-[#030712] transition-colors" />
                  </>
                )}
              </div>
            </button>
          </form>

          <div className="mt-10 text-center">
            <p className="text-sm text-gray-500">
              Novo no ecossistema?{" "}
              <Link
                href="/register"
                className="text-[#d4af37] hover:text-[#f0dfa0] font-bold transition-all decoration-[#d4af37]/20 underline-offset-4 hover:underline"
              >
                Inicie sua Mentoria
              </Link>
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
