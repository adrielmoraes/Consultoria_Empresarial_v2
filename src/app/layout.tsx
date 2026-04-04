import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

export const viewport: Viewport = {
  themeColor: "#030712",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export const metadata: Metadata = {
  title: "Hive Mind - Consultoria Multi-Agentes com IA",
  description:
    "Sessões de consultoria em tempo real com um painel de 5 especialistas de IA. Receba um Plano de Execução completo para o seu projeto.",
  keywords: ["mentoria", "IA", "consultoria", "multi-agentes", "startup", "negócios", "hive mind"],
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Hive Mind",
  },
  formatDetection: {
    telephone: false,
  },
  icons: {
    icon: "/logo-icon.svg",
    shortcut: "/logo-icon.svg",
    apple: "/logo-icon.svg",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans antialiased`} suppressHydrationWarning>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
