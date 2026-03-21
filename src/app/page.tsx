"use client";

import { Header } from "@/components/header";
import { motion } from "framer-motion";
import {
  Brain,
  Users,
  FileText,
  Zap,
  Shield,
  TrendingUp,
  Code,
  Gavel,
  ArrowRight,
  Check,
  Sparkles,
  MessageSquare,
  Video,
} from "lucide-react";
import Link from "next/link";

const fadeUp: any = {
  hidden: { opacity: 0, y: 30 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.1, duration: 0.6, ease: "easeOut" },
  }),
};

const specialists = [
  {
    icon: TrendingUp,
    name: "CFO - Estratégia Financeira",
    description: "Viabilidade econômica, precificação, custos e projeções financeiras.",
    color: "from-emerald-400 to-teal-500",
  },
  {
    icon: Gavel,
    name: "Advogado - Jurídico",
    description: "Conformidade, contratos, LGPD, constituição de empresa e riscos legais.",
    color: "from-amber-400 to-orange-500",
  },
  {
    icon: Users,
    name: "CMO - Marketing & Vendas",
    description: "Aquisição de clientes, branding, go-to-market e estratégia de vendas.",
    color: "from-pink-400 to-rose-500",
  },
  {
    icon: Code,
    name: "CTO - Tecnologia",
    description: "Infraestrutura, stack, viabilidade técnica e escalabilidade.",
    color: "from-blue-400 to-cyan-500",
  },
];

const features = [
  {
    icon: Video,
    title: "Reunião em Tempo Real",
    description: "Converse por voz com 5 especialistas de IA em uma sala de vídeo interativa.",
  },
  {
    icon: MessageSquare,
    title: "Debate Multi-Agentes",
    description: "Os especialistas debatem entre si sobre seu projeto, complementando análises.",
  },
  {
    icon: FileText,
    title: "Plano de Execução em PDF",
    description: "Ao final, receba um plano passo a passo detalhado e pronto para executar.",
  },
  {
    icon: Zap,
    title: "Latência Ultrabaixa",
    description: "Respostas em menos de 2 segundos, com sincronia labial nos avatares.",
  },
  {
    icon: Shield,
    title: "Seguro e Privado",
    description: "Seus dados são criptografados e nunca compartilhados com terceiros.",
  },
  {
    icon: Sparkles,
    title: "IA de Última Geração",
    description: "Powered by Gemini, com janelas de contexto massivas para sessões longas.",
  },
];

const plans = [
  {
    name: "Sessão Avulsa",
    price: "R$ 49",
    period: "por sessão",
    description: "Ideal para quem quer experimentar ou resolver uma dúvida pontual.",
    features: [
      "1 sessão de mentoria",
      "5 especialistas de IA",
      "Plano de Execução em PDF",
      "30 minutos de reunião",
    ],
    cta: "Comprar Sessão",
    popular: false,
  },
  {
    name: "Profissional",
    price: "R$ 149",
    period: "por mês",
    description: "Para empreendedores que precisam de mentorias regulares.",
    features: [
      "5 sessões por mês",
      "5 especialistas de IA",
      "Plano de Execução em PDF",
      "60 minutos por reunião",
      "Histórico de projetos",
      "Suporte prioritário",
    ],
    cta: "Assinar Agora",
    popular: true,
  },
  {
    name: "Enterprise",
    price: "R$ 399",
    period: "por mês",
    description: "Para equipes e empresas que necessitam de mentorias ilimitadas.",
    features: [
      "Sessões ilimitadas",
      "5 especialistas de IA",
      "Plano de Execução em PDF",
      "Sem limite de tempo",
      "Histórico completo",
      "Suporte dedicado",
      "API access",
    ],
    cta: "Falar com Vendas",
    popular: false,
  },
];

const steps = [
  {
    step: "01",
    title: "Crie seu Projeto",
    description: "Dê um nome ao seu projeto e descreva brevemente sua ideia ou problema.",
  },
  {
    step: "02",
    title: "Entre na Sala",
    description: "A apresentadora e os 4 especialistas te recepcionam em uma sala de vídeo.",
  },
  {
    step: "03",
    title: "Converse e Debata",
    description: "Fale por voz. Os especialistas debatem entre si para cobrir todos os ângulos.",
  },
  {
    step: "04",
    title: "Receba seu Plano",
    description: "Ao final, um Plano de Execução detalhado em PDF é gerado para download.",
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen">
      <Header />

      {/* Hero Section */}
      <section className="relative pt-32 pb-20 px-4 overflow-hidden">
        {/* Background effects */}
        <div className="absolute inset-0 bg-grid opacity-30" />
        <div className="absolute top-20 left-1/4 w-96 h-96 bg-indigo-500/20 rounded-full blur-3xl" />
        <div className="absolute bottom-0 right-1/4 w-96 h-96 bg-purple-500/20 rounded-full blur-3xl" />

        <div className="relative max-w-6xl mx-auto text-center">
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5 }}
            className="inline-flex items-center gap-2 bg-indigo-500/10 border border-indigo-500/20 rounded-full px-4 py-2 mb-6"
          >
            <Sparkles className="w-4 h-4 text-indigo-400" />
            <span className="text-sm text-indigo-400 font-medium">
              Powered by Gemini AI & Multi-Agentes
            </span>
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1 }}
            className="text-5xl sm:text-6xl lg:text-7xl font-bold tracking-tight mb-6"
          >
            Seu Conselho de{" "}
            <span className="gradient-text">Especialistas</span>
            <br />
            em Inteligência Artificial
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="text-lg sm:text-xl text-gray-500 dark:text-gray-400 max-w-3xl mx-auto mb-10"
          >
            Entre em uma sala de vídeo com 5 agentes de IA especializados. Eles debatem,
            analisam e criam um Plano de Execução completo para o seu projeto — tudo em
            tempo real.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="flex flex-col sm:flex-row items-center justify-center gap-4"
          >
            <Link href="/register" className="btn-primary text-lg px-8 py-4 flex items-center gap-2">
              Iniciar Mentoria Grátis <ArrowRight className="w-5 h-5" />
            </Link>
            <Link href="#how-it-works" className="btn-secondary text-lg px-8 py-4">
              Como Funciona
            </Link>
          </motion.div>

          {/* Pentaptych Preview */}
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.5 }}
            className="mt-16 max-w-5xl mx-auto"
          >
            <div className="glass-card p-4 sm:p-6">
              <div className="grid grid-cols-5 gap-2 sm:gap-3">
                {["Apresentadora", "CFO", "Advogado", "CMO", "CTO"].map(
                  (name, i) => (
                    <div
                      key={name}
                      className={`relative aspect-[3/4] rounded-xl overflow-hidden border-2 ${
                        i === 0
                          ? "border-indigo-500/50 active-speaker"
                          : "border-white/10"
                      } bg-gradient-to-br ${
                        i === 0
                          ? "from-indigo-900/50 to-purple-900/50"
                          : i === 1
                          ? "from-emerald-900/50 to-teal-900/50"
                          : i === 2
                          ? "from-amber-900/50 to-orange-900/50"
                          : i === 3
                          ? "from-pink-900/50 to-rose-900/50"
                          : "from-blue-900/50 to-cyan-900/50"
                      }`}
                    >
                      <div className="absolute inset-0 flex items-center justify-center">
                        <div className="w-12 h-12 sm:w-16 sm:h-16 rounded-full bg-white/10 flex items-center justify-center">
                          <Brain className="w-6 h-6 sm:w-8 sm:h-8 text-white/40" />
                        </div>
                      </div>
                      <div className="absolute bottom-0 left-0 right-0 p-2 bg-black/50 backdrop-blur-sm">
                        <p className="text-xs sm:text-sm text-white font-medium text-center truncate">
                          {name}
                        </p>
                      </div>
                    </div>
                  )
                )}
              </div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Specialists Section */}
      <section className="py-20 px-4">
        <div className="max-w-6xl mx-auto">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <motion.h2
              variants={fadeUp}
              custom={0}
              className="text-3xl sm:text-4xl font-bold mb-4"
            >
              Seu Painel de <span className="gradient-text">Especialistas</span>
            </motion.h2>
            <motion.p
              variants={fadeUp}
              custom={1}
              className="text-gray-500 dark:text-gray-400 max-w-2xl mx-auto"
            >
              Quatro especialistas de IA debatem seu projeto em tempo real,
              orquestrados por uma Apresentadora inteligente.
            </motion.p>
          </motion.div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {specialists.map((spec, i) => (
              <motion.div
                key={spec.name}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                variants={fadeUp}
                custom={i + 2}
                className="glass-card p-6"
              >
                <div
                  className={`w-12 h-12 rounded-xl bg-gradient-to-r ${spec.color} flex items-center justify-center mb-4`}
                >
                  <spec.icon className="w-6 h-6 text-white" />
                </div>
                <h3 className="text-lg font-semibold mb-2">{spec.name}</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {spec.description}
                </p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="py-20 px-4 bg-gray-50/50 dark:bg-gray-900/30">
        <div className="max-w-6xl mx-auto">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <motion.h2
              variants={fadeUp}
              custom={0}
              className="text-3xl sm:text-4xl font-bold mb-4"
            >
              Por que escolher a <span className="gradient-text">Mentoria AI</span>?
            </motion.h2>
          </motion.div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((feature, i) => (
              <motion.div
                key={feature.title}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                variants={fadeUp}
                custom={i}
                className="glass-card p-6"
              >
                <div className="w-10 h-10 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center mb-4">
                  <feature.icon className="w-5 h-5 text-indigo-400" />
                </div>
                <h3 className="text-lg font-semibold mb-2">{feature.title}</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {feature.description}
                </p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* How It Works Section */}
      <section id="how-it-works" className="py-20 px-4">
        <div className="max-w-6xl mx-auto">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <motion.h2
              variants={fadeUp}
              custom={0}
              className="text-3xl sm:text-4xl font-bold mb-4"
            >
              Como <span className="gradient-text">Funciona</span>
            </motion.h2>
          </motion.div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {steps.map((step, i) => (
              <motion.div
                key={step.step}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                variants={fadeUp}
                custom={i}
                className="relative"
              >
                {i < steps.length - 1 && (
                  <div className="hidden lg:block absolute top-8 left-full w-full h-px bg-gradient-to-r from-indigo-500/50 to-transparent z-10" />
                )}
                <div className="glass-card p-6 text-center">
                  <span className="text-4xl font-black gradient-text">
                    {step.step}
                  </span>
                  <h3 className="text-lg font-semibold mt-4 mb-2">
                    {step.title}
                  </h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    {step.description}
                  </p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing Section */}
      <section id="pricing" className="py-20 px-4 bg-gray-50/50 dark:bg-gray-900/30">
        <div className="max-w-6xl mx-auto">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <motion.h2
              variants={fadeUp}
              custom={0}
              className="text-3xl sm:text-4xl font-bold mb-4"
            >
              Planos e <span className="gradient-text">Preços</span>
            </motion.h2>
            <motion.p
              variants={fadeUp}
              custom={1}
              className="text-gray-500 dark:text-gray-400 max-w-2xl mx-auto"
            >
              Escolha o plano ideal para o seu momento. Cancele quando quiser.
            </motion.p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-5xl mx-auto">
            {plans.map((plan, i) => (
              <motion.div
                key={plan.name}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                variants={fadeUp}
                custom={i}
                className={`glass-card p-8 relative ${
                  plan.popular
                    ? "border-indigo-500/50 ring-1 ring-indigo-500/20"
                    : ""
                }`}
              >
                {plan.popular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <span className="bg-gradient-to-r from-indigo-500 to-purple-600 text-white text-xs font-bold px-3 py-1 rounded-full">
                      Mais Popular
                    </span>
                  </div>
                )}
                <h3 className="text-xl font-bold mb-1">{plan.name}</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                  {plan.description}
                </p>
                <div className="mb-6">
                  <span className="text-4xl font-black gradient-text">
                    {plan.price}
                  </span>
                  <span className="text-sm text-gray-500 dark:text-gray-400 ml-1">
                    {plan.period}
                  </span>
                </div>
                <ul className="space-y-3 mb-8">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-center gap-2 text-sm">
                      <Check className="w-4 h-4 text-indigo-400 flex-shrink-0" />
                      <span className="text-gray-600 dark:text-gray-300">{f}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href="/register"
                  className={`block text-center w-full py-3 rounded-xl font-semibold transition-all ${
                    plan.popular
                      ? "btn-primary"
                      : "btn-secondary"
                  }`}
                >
                  {plan.cta}
                </Link>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 px-4">
        <div className="max-w-4xl mx-auto text-center">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
          >
            <motion.h2
              variants={fadeUp}
              custom={0}
              className="text-3xl sm:text-4xl font-bold mb-4"
            >
              Pronto para ter sua{" "}
              <span className="gradient-text">Mentoria com IA</span>?
            </motion.h2>
            <motion.p
              variants={fadeUp}
              custom={1}
              className="text-gray-500 dark:text-gray-400 mb-8 max-w-2xl mx-auto"
            >
              Junte-se a centenas de empreendedores que já receberam consultoria
              estratégica com nosso painel de especialistas.
            </motion.p>
            <motion.div variants={fadeUp} custom={2}>
              <Link
                href="/register"
                className="btn-primary text-lg px-10 py-4 inline-flex items-center gap-2"
              >
                Começar Agora <ArrowRight className="w-5 h-5" />
              </Link>
            </motion.div>
          </motion.div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/10 py-12 px-4">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-indigo-400" />
            <span className="font-bold gradient-text">Mentoria AI</span>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            © 2026 Mentoria AI. Todos os direitos reservados.
          </p>
        </div>
      </footer>
    </div>
  );
}
