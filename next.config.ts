import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,
  allowedDevOrigins: [
    "*.replit.dev",
    "*.repl.co",
    "*.replit.app",
    "*.picard.replit.dev",
    "*.kirk.replit.dev",
  ],
  // Desativa cache automático em desenvolvimento
  experimental: {
    // Para páginas client-side, não faz sentido ter PPR
    ppr: false,
  },
  // Garante que não há revalidação automática
  staticPageGenerationTimeout: 180,
};

export default nextConfig;
