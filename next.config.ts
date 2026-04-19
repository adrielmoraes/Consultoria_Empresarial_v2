import type { NextConfig } from "next";

const replitDevDomain = process.env.REPLIT_DEV_DOMAIN;

const allowedDevOrigins = [
  "*.replit.dev",
  "*.repl.co",
  "*.replit.app",
];

if (replitDevDomain) {
  allowedDevOrigins.push(replitDevDomain);
}

const nextConfig: NextConfig = {
  reactCompiler: true,
  allowedDevOrigins,
  experimental: {
    ppr: false,
  },
  staticPageGenerationTimeout: 180,
};

export default nextConfig;
