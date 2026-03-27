"use client";

import Link from "next/link";
import { ThemeToggle } from "./theme-toggle";
import { motion } from "framer-motion";

export function Header() {
  return (
    <motion.header
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="fixed top-0 left-0 right-0 z-50 border-b border-white/10 bg-white/70 dark:bg-gray-950/70 backdrop-blur-xl"
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo — ícone SVG (sem texto) + nome separado */}
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-r from-[#d4af37] to-[#b08d24] rounded-lg blur-md opacity-60 group-hover:opacity-100 transition-opacity" />
              <div className="relative p-1 rounded-lg">
                <img src="/logo-icon.svg" alt="Hive Mind" className="w-8 h-8" />
              </div>
            </div>
            <span className="text-xl font-bold bg-gradient-to-r from-[#d4af37] to-[#e6c86a] bg-clip-text text-transparent">
              Hive Mind
            </span>
          </Link>

          {/* Nav */}
          <nav className="hidden md:flex items-center gap-8">
            <Link href="#features" className="text-sm text-gray-600 dark:text-gray-400 hover:text-[#d4af37] dark:hover:text-[#e6c86a] transition-colors">
              Recursos
            </Link>
            <Link href="#pricing" className="text-sm text-gray-600 dark:text-gray-400 hover:text-[#d4af37] dark:hover:text-[#e6c86a] transition-colors">
              Preços
            </Link>
            <Link href="#how-it-works" className="text-sm text-gray-600 dark:text-gray-400 hover:text-[#d4af37] dark:hover:text-[#e6c86a] transition-colors">
              Como Funciona
            </Link>
          </nav>

          {/* Actions */}
          <div className="flex items-center gap-3">
            <ThemeToggle />
            <Link
              href="/login"
              className="text-sm text-gray-700 dark:text-gray-300 hover:text-[#d4af37] dark:hover:text-[#e6c86a] transition-colors"
            >
              Entrar
            </Link>
            <Link
              href="/register"
              className="relative group"
            >
              <div className="absolute inset-0 bg-gradient-to-r from-[#d4af37] to-[#b08d24] rounded-lg blur-sm opacity-60 group-hover:opacity-100 transition-opacity" />
              <span className="relative block bg-gradient-to-r from-[#d4af37] to-[#b08d24] text-[#0a0a0a] text-sm font-semibold px-4 py-2 rounded-lg hover:shadow-lg hover:shadow-[#d4af37]/25 transition-shadow">
                Começar Grátis
              </span>
            </Link>
          </div>
        </div>
      </div>
    </motion.header>
  );
}
