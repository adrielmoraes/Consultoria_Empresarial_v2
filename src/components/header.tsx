"use client";

import Link from "next/link";
import { ThemeToggle } from "./theme-toggle";
import { InstallAppButton } from "./install-app-button";
import { motion } from "framer-motion";

export function Header() {
  return (
    <motion.header
      initial={{ y: -100, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.8, ease: "easeOut" }}
      className="fixed top-0 left-0 right-0 z-50 border-b border-white/5 bg-[#ffffff]/80 dark:bg-[#030712]/80 backdrop-blur-2xl"
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-20">
          {/* Logo Section */}
          <Link href="/" className="flex items-center gap-3 group">
            <div className="relative">
              <div className="absolute inset-[-4px] bg-[#d4af37]/20 rounded-xl blur-lg opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
              <div className="relative w-11 h-11 rounded-xl bg-[#0a0a0f] border border-[#d4af37]/30 shadow-[0_0_15px_rgba(212,175,55,0.15)] flex items-center justify-center transform group-hover:scale-105 transition-transform duration-300 group-hover:border-[#d4af37]/60">
                <img src="/logo-icon.svg" alt="Hive Mind" className="w-7 h-7 object-contain" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
              </div>
            </div>
            <div className="flex flex-col">
              <span className="text-xl font-bold tracking-tight bg-gradient-to-r from-[#d4af37] via-[#f0dfa0] to-[#b08d24] bg-clip-text text-transparent">
                Hive Mind
              </span>
              <span className="text-[10px] font-medium uppercase tracking-[0.2em] text-gray-500 dark:text-gray-400 group-hover:text-[#d4af37] transition-colors">
                Enterprise AI
              </span>
            </div>
          </Link>

          {/* Navigation */}
          <nav className="hidden lg:flex items-center gap-10">
            {['Recursos', 'Preços', 'Metodologia', 'Empresa'].map((item) => (
              <Link 
                key={item}
                href={`#${item.toLowerCase()}`} 
                className="text-sm font-medium text-gray-500 dark:text-gray-400 hover:text-[#d4af37] dark:hover:text-[#f0dfa0] transition-all relative group"
              >
                {item}
                <span className="absolute -bottom-1 left-0 w-0 h-[1px] bg-[#d4af37] transition-all duration-300 group-hover:w-full" />
              </Link>
            ))}
          </nav>

          {/* Action Area */}
          <div className="flex items-center gap-6">
            <div className="hidden sm:flex items-center gap-4">
              <InstallAppButton />
              <ThemeToggle />
            </div>
            
            <div className="h-6 w-[1px] bg-white/10 hidden sm:block" />

            <div className="flex items-center gap-4">
              <Link
                href="/login"
                className="text-sm font-semibold text-gray-400 hover:text-white transition-colors"
              >
                Log In
              </Link>
              
              <Link
                href="/register"
                className="relative group overflow-hidden"
              >
                <div className="absolute inset-0 bg-gradient-to-r from-[#b08d24] to-[#d4af37] p-[1px] rounded-xl">
                  <div className="w-full h-full bg-[#030712] group-hover:bg-transparent rounded-[11px] transition-all duration-300" />
                </div>
                <span className="relative block px-6 py-2.5 text-sm font-bold text-white group-hover:text-[#030712] transition-colors">
                  Inicie Agora
                </span>
              </Link>
            </div>
          </div>
        </div>
      </div>
    </motion.header>
  );
}
