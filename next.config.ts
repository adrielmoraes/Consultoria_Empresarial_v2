import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,
  allowedDevOrigins: [
    "beadc9d4-ac2a-4b88-bf92-4785c30355ee-00-q7hd15bdm2fx.picard.replit.dev",
    "*.replit.dev",
    "*.repl.co",
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
