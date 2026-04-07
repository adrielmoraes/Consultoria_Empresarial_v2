"use client";

import { Header } from "@/components/header";
import { motion } from "framer-motion";
import type { Variants } from "framer-motion";
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

const fadeUp: Variants = {
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
    description: "Modelos de linguagem avançados com janelas de contexto massivas para sessões longas.",
  },
];

const plans = [
  {
    name: "Sessão Avulsa",
    price: "R$ 149,90",
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
    price: "R$ 399,90",
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
    <div className="min-h-screen bg-[#030712] text-white selection:bg-[#d4af37]/30">
      <Header />

      {/* Hero Section */}
      <section className="relative pt-40 pb-24 px-4 overflow-hidden">
        {/* Elite Background Effects */}
        <div className="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/stardust.png')] opacity-20 pointer-events-none" />
        <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-[#b08d24]/10 rounded-full blur-[120px] animate-orb" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[50%] h-[50%] bg-[#d4af37]/10 rounded-full blur-[120px] animate-orb" style={{ animationDelay: '-10s' }} />
        
        <div className="relative max-w-7xl mx-auto text-center z-10">
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8 }}
            className="inline-flex items-center gap-2 bg-gradient-to-r from-[#d4af37]/10 to-[#b08d24]/10 border border-[#d4af37]/20 rounded-full px-6 py-2.5 mb-10 backdrop-blur-md shadow-[0_0_20px_rgba(212,175,55,0.1)]"
          >
            <Sparkles className="w-4 h-4 text-[#d4af37]" />
            <span className="text-xs font-black uppercase tracking-[0.2em] text-[#d4af37]">
              O Futuro da Consultoria Estratégica
            </span>
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.2 }}
            className="text-6xl sm:text-7xl lg:text-8xl font-black tracking-tighter mb-8 leading-[0.9] uppercase"
          >
            Seu Conselho de<br />
            <span className="bg-gradient-to-r from-[#d4af37] via-[#f0dfa0] to-[#b08d24] bg-clip-text text-transparent italic">Elite</span> Executiva
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.4 }}
            className="text-lg sm:text-xl text-gray-400 max-w-3xl mx-auto mb-12 leading-relaxed font-medium"
          >
            Entre em uma sala de comando com 5 agentes de IA de nível sênior. 
            Eles debatem, desafiam suas ideias e consolidam um 
            <span className="text-white border-b border-[#d4af37]/30 px-1 inline-block">Plano de Execução Implacável</span> em tempo real.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.6 }}
            className="flex flex-col sm:flex-row items-center justify-center gap-6"
          >
            <Link 
              href="/register" 
              className="group relative px-10 py-5 bg-gradient-to-r from-[#b08d24] to-[#d4af37] rounded-2xl shadow-[0_0_40px_rgba(212,175,55,0.2)] hover:shadow-[0_0_60px_rgba(212,175,55,0.4)] transition-all duration-500 transform hover:-translate-y-1"
            >
              <div className="flex items-center gap-3">
                <span className="text-lg font-black text-[#030712] uppercase tracking-tighter">Convocação do Comitê</span>
                <ArrowRight className="w-5 h-5 text-[#030712]" />
              </div>
            </Link>
            
            <Link 
              href="#how-it-works" 
              className="px-10 py-5 rounded-2xl bg-white/5 border border-white/10 text-lg font-bold text-white hover:bg-white/10 transition-all backdrop-blur-md"
            >
              Ver Metodologia
            </Link>
          </motion.div>

          {/* Pentaptych Elite Preview */}
          <motion.div
            initial={{ opacity: 0, y: 60 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1, delay: 0.8 }}
            className="mt-20 max-w-5xl mx-auto relative group"
          >
            <div className="absolute -inset-1 bg-gradient-to-r from-[#d4af37]/20 via-transparent to-[#b08d24]/20 rounded-[40px] blur-2xl opacity-50 group-hover:opacity-100 transition-opacity duration-1000" />
            <div className="relative glass-card-premium p-4 sm:p-2 border-white/5 bg-black/60">
              <div className="grid grid-cols-5 gap-2 sm:gap-4 overflow-hidden rounded-[30px]">
                {[
                  { name: "Carlos (CFO)", color: "from-emerald-600 to-teal-700", icon: TrendingUp },
                  { name: "Daniel (LEGAL)", color: "from-amber-600 to-orange-700", icon: Gavel },
                  { name: "Apresentadora", color: "from-[#d4af37] to-[#b08d24]", icon: Brain },
                  { name: "Rodrigo (CMO)", color: "from-pink-600 to-rose-700", icon: Users },
                  { name: "Ana (CTO)", color: "from-blue-600 to-cyan-700", icon: Code }
                ].map((spec, i) => (
                  <div
                    key={spec.name}
                    className={`relative aspect-[3/5] overflow-hidden group/agent transition-all duration-500 ${
                      i === 2 ? "scale-105 z-10" : "scale-100"
                    }`}
                  >
                    <div className={`absolute inset-0 bg-gradient-to-br ${spec.color} opacity-20`} />
                    {i === 2 && (
                      <div className="absolute -inset-[1px] bg-gradient-to-br from-[#d4af37] via-[#f0dfa0] to-[#b08d24] rounded-sm opacity-60 animate-pulse -z-0" />
                    )}
                    <div className="absolute inset-0 bg-[#030712]/60 backdrop-blur-[2px]" />
                    <div className="absolute inset-0 flex flex-col items-center justify-center p-2 text-center">
                      <div className={`w-12 h-12 rounded-full flex items-center justify-center bg-gradient-to-br ${spec.color} shadow-2xl mb-3 ${i === 2 ? "ring-2 ring-[#d4af37]/50 ring-offset-2 ring-offset-[#030712]" : ""}`}>
                        <spec.icon className="w-6 h-6 text-white" />
                      </div>
                      <p className="text-[10px] font-black uppercase text-white tracking-widest">{spec.name}</p>
                    </div>
                    {i === 2 && (
                      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-1 bg-[#d4af37] px-2 py-0.5 rounded-full scale-[0.8]">
                        <div className="w-1 h-1 bg-black rounded-full animate-pulse" />
                        <span className="text-[8px] font-black text-black">LIVE</span>
                      </div>
                    )}
                  </div>
                ))}
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
              Por que escolher o <span className="gradient-text">Hive Mind</span>?
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
                <div className="w-10 h-10 rounded-lg bg-[#d4af37]/10 border border-[#d4af37]/20 flex items-center justify-center mb-4">
                  <feature.icon className="w-5 h-5 text-[#d4af37]" />
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
                  <div className="hidden lg:block absolute top-8 left-full w-full h-px bg-gradient-to-r from-[#d4af37]/50 to-transparent z-10" />
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
                    ? "border-[#d4af37]/50 ring-1 ring-[#d4af37]/20"
                    : ""
                }`}
              >
                {plan.popular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <span className="bg-gradient-to-r from-[#d4af37] to-[#b08d24] text-[#0a0a0a] text-xs font-bold px-3 py-1 rounded-full">
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
                      <Check className="w-4 h-4 text-[#d4af37] flex-shrink-0" />
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
              Pronto para evoluir com o{" "}
              <span className="gradient-text">Hive Mind</span>?
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
      <footer className="border-t border-white/5 py-20 px-4 bg-[#010307]">
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-col md:flex-row items-center justify-between gap-12">
            <div className="flex flex-col items-center md:items-start gap-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 p-1 rounded-xl bg-[#0a0a0f] border border-[#d4af37]/30 shadow-[0_0_15px_rgba(212,175,55,0.15)] flex items-center justify-center">
                  <img src="/logo-icon.svg?v=2" alt="Hive Mind" className="w-full h-full object-contain" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
                </div>
                <span className="text-2xl font-black bg-gradient-to-r from-[#d4af37] via-[#f0dfa0] to-[#b08d24] bg-clip-text text-transparent uppercase tracking-tight">Hive Mind</span>
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-500 font-medium max-w-xs text-center md:text-left">
                Redefinindo os limites da consultoria executiva com inteligência artificial de elite.
              </p>
            </div>
            
            <div className="flex gap-12">
               <div className="flex flex-col gap-4">
                  <span className="text-xs font-black uppercase tracking-widest text-[#d4af37]">Plataforma</span>
                  <Link href="#features" className="text-sm text-gray-500 hover:text-white transition-colors">Recursos</Link>
                  <Link href="#pricing" className="text-sm text-gray-500 hover:text-white transition-colors">Planos</Link>
               </div>
               <div className="flex flex-col gap-4">
                  <span className="text-xs font-black uppercase tracking-widest text-[#d4af37]">Empresa</span>
                  <Link href="#" className="text-sm text-gray-500 hover:text-white transition-colors">Segurança</Link>
                  <Link href="#" className="text-sm text-gray-500 hover:text-white transition-colors">Contato</Link>
               </div>
            </div>
          </div>
          
          <div className="mt-20 pt-10 border-t border-white/5 flex flex-col md:flex-row justify-between items-center gap-6">
            <p className="text-xs text-gray-600 uppercase font-black tracking-widest">
              © 2026 Hive Mind Enterprise. Todos os direitos reservados.
            </p>
            <div className="flex gap-8">
               <Link href="#" className="text-[10px] uppercase font-black text-gray-700 hover:text-gray-400 tracking-widest">Privacy Policy</Link>
               <Link href="#" className="text-[10px] uppercase font-black text-gray-700 hover:text-gray-400 tracking-widest">Terms of Service</Link>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
