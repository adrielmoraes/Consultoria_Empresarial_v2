import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "Hive Mind - Consultoria Multi-Agentes com IA",
  description:
    "Sessões de consultoria em tempo real com um painel de 5 especialistas de IA. Receba um Plano de Execução completo para o seu projeto.",
  keywords: ["mentoria", "IA", "consultoria", "multi-agentes", "startup", "negócios", "hive mind"],
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
