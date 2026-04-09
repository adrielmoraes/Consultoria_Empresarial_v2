"use client";

import { Header } from "@/components/header";
import { motion, AnimatePresence } from "framer-motion";
import type { Variants } from "framer-motion";
import { useState, useEffect } from "react";
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
  Building2,
  Target,
  Handshake,
  LockKeyhole,
  Mail,
  PhoneCall,
  CalendarCheck2,
  Flame,
  ChevronRight,
  ChevronLeft
} from "lucide-react";
import Link from "next/link";
import Image from "next/image";

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 30 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.1, duration: 0.6, ease: "easeOut" },
  }),
};

// ─── DADOS DO CARROSSEL DE PERSUASÃO (PNL) ──────────────────────────────────
const persuasionSlides = [
  {
    title: "O Peso Invisível da Liderança",
    text: "Você toma dezenas de decisões arriscadas todos os dias, muitas vezes baseadas apenas na intuição suportando a pressão do erro sozinho. Na alta gestão, o 'achismo' não dói apenas no ego — ele corrói silenciosamente o seu caixa e atrasa seu crescimento.",
    icon: Flame,
    color: "from-orange-500/20 to-red-500/10",
    border: "border-orange-500/30",
  },
  {
    title: "O Refinamento Pela Verdade",
    text: "Boas ideias morrem na hesitação. A Hive Mind transforma suas dúvidas no mais alto nível de ataque coordenado. Em menos de 30 minutos, sua ideia é testada por inteligências críticas incisivas, lapidada contra falhas fatais e forjada para gerar lucro real.",
    icon: Target,
    color: "from-blue-500/20 to-cyan-500/10",
    border: "border-cyan-500/30",
  },
  {
    title: "O Conselho Que Custaria Milhões",
    text: "Contratar um CFO, CMO, CTO e um Advogado de elite sob demanda custaria facilmente R$ 80.000 mensais com consultorias tradicionais. Aqui, o ápice do conhecimento humano, estruturado pela IA, opera ao seu favor em tempo real, 24 horas por dia.",
    icon: TrendingUp,
    color: "from-emerald-500/20 to-teal-500/10",
    border: "border-emerald-500/30",
  },
  {
    title: "Certeza Absoluta na Execução",
    text: "Imagine a tranquilidade de dormir sabendo que seu próximo passo de negócios foi analisado com frieza milimétrica por 5 inteligências focadas unicamente na sua proteção e aceleração. Você não recebe 'dicas' rasas, você adquire um plano infalível em PDF.",
    icon: Shield,
    color: "from-[#d4af37]/20 to-[#b08d24]/10",
    border: "border-[#d4af37]/40",
  }
];

function PersuasionCarousel() {
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrent((prev) => (prev + 1) % persuasionSlides.length);
    }, 7000);
    return () => clearInterval(timer);
  }, []);

  const slide = persuasionSlides[current];
  const Icon = slide.icon;

  return (
    <div className="w-full max-w-4xl mx-auto mt-16 relative">
      <div className="absolute -inset-1 bg-linear-to-r from-[#d4af37]/20 to-[#b08d24]/20 rounded-3xl blur-2xl opacity-40" />
      
      <div className="relative bg-[#0a0f1c]/90 border border-[#d4af37]/20 rounded-3xl p-8 sm:p-12 backdrop-blur-xl overflow-hidden min-h-[280px] flex items-center shadow-2xl">
        <AnimatePresence mode="wait">
          <motion.div
            key={current}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className="w-full flex flex-col md:flex-row items-center gap-8 md:gap-12"
          >
            <div className={`w-20 h-20 shrink-0 rounded-2xl bg-linear-to-br ${slide.color} border ${slide.border} flex items-center justify-center shadow-inner`}>
              <Icon className="w-10 h-10 text-white" />
            </div>
            <div className="flex-1 text-center md:text-left">
              <h3 className="text-2xl sm:text-3xl font-black text-white mb-4 tracking-tight uppercase">
                {slide.title}
              </h3>
              <p className="text-gray-300 sm:text-lg leading-relaxed font-medium">
                {slide.text}
              </p>
            </div>
          </motion.div>
        </AnimatePresence>

        {/* Carousel Controls Container */}
        <div className="absolute bottom-6 left-0 right-0 flex justify-center gap-2 z-10">
          {persuasionSlides.map((_, i) => (
            <button
              key={i}
              onClick={() => setCurrent(i)}
              className={`h-1.5 rounded-full transition-all duration-500 ease-out ${
                current === i ? "w-10 bg-[#d4af37]" : "w-3 bg-white/20 hover:bg-white/40"
              }`}
              aria-label={`Go to slide ${i + 1}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

const specialists = [
  {
    icon: TrendingUp,
    name: "CFO Financeiro",
    description: "Ele corta a sangria de caixa. Valida sua viabilidade econômica real, projeta custos insanos e encontra lucro onde você via prejuízo.",
    color: "from-emerald-400 to-teal-500",
  },
  {
    icon: Gavel,
    name: "Consultor Jurídico",
    description: "Blindagem societária imediata. Previne processos milionários antes que aconteçam e fecha todas as brechas dos seus contratos.",
    color: "from-amber-400 to-orange-500",
  },
  {
    icon: Users,
    name: "CMO em Marketing",
    description: "Orquestra a tração. Desenha a estratégia de ataque ao mercado e posicionamento de vendas impossível de ser ignorada.",
    color: "from-pink-400 to-rose-500",
  },
  {
    icon: Code,
    name: "CTO em Tecnologia",
    description: "A raiz da escalabilidade. Audita sua stack tecnológica, elimina arquiteturas frágeis e garante a estabilidade do sistema.",
    color: "from-blue-400 to-cyan-500",
  },
];

const features = [
  {
    icon: Video,
    title: "Decisão Sob Controle em Tempo Real",
    description: "Faça um pitch da sua ideia por voz, cara a cara com inteligências focadas em destruí-la para reconstruir algo à prova de balas.",
  },
  {
    icon: MessageSquare,
    title: "Inteligência Coletiva Cruzada",
    description: "Sua ideia de marketing é legal, mas é viável financeiramente? Os agentes debatem entre si para não deixar pontos cegos na mesa.",
  },
  {
    icon: FileText,
    title: "Estratégia Materializada em PDF",
    description: "Conversar não basta. Você sai com um roteiro rígido de passos acionáveis, documentado e formatado para a sua equipe iniciar hoje.",
  },
  {
    icon: Zap,
    title: "Latência Neural Imediata",
    description: "Esqueça chats de texto demorados. A conexão é vocal, humana, cortante e veloz (menos de 2s), orquestrada por sincronia labial AI.",
  },
  {
    icon: Shield,
    title: "Sigilo Corporativo Inquebrável",
    description: "O maior diferencial competitivo é o segredo. Seus layouts, dados e ideias são criptografados de ponta a ponta e pulverizados do histórico de treino.",
  },
  {
    icon: Sparkles,
    title: "Contexto Analítico Profundo",
    description: "Você chegou com os problemas, nós mantemos todo o histórico na memória durante a conversa para gerar resoluções complexas de longo prazo.",
  },
];

const plans = [
  {
    name: "Sessão Avulsa",
    price: "R$ 149,90",
    period: "por sessão",
    description: "Custa menos que um almoço executivo, salva você de prejuízos irreversíveis e traz lucidez instantânea.",
    features: [
      "1 sala de guerra instantânea",
      "5 especialistas desafiando você",
      "Plano PDF para agir no mesmo dia",
      "30 minutos intensos de clareza",
    ],
    cta: "Antecipar Decisão Estratégica",
    popular: false,
  },
  {
    name: "Acesso Profissional",
    price: "R$ 399,90",
    period: "por mês",
    description: "Uma fração insignificante do risco de errar. Seu próprio conselho direcional operando em alta cadência.",
    features: [
      "5 batalhas intelectuais por mês",
      "Acesso ao board de 5 especialistas",
      "Arquivos em PDF vitalícios",
      "Sessões expandidas de 60 minutos",
      "Histórico de memórias criptografadas",
      "Respostas prioritárias no cluster",
    ],
    cta: "Blindar as Operações da Empresa",
    popular: true,
  },
];

const steps = [
  {
    step: "01",
    title: "Evidência Inicial",
    description: "Defina o escopo da sua angústia e da ideia. O que está travando o crescimento do seu projeto?",
  },
  {
    step: "02",
    title: "O Ponto de Ignição",
    description: "A reunião se abre. A apresentadora inicia o protocolo agressivo pedindo seus desafios a fundo.",
  },
  {
    step: "03",
    title: "Mesa Redonda Implacável",
    description: "O debriefing mais rápido da sua vida. Você argumenta, e a IA calcula a eficiência da ação.",
  },
  {
    step: "04",
    title: "O Roteiro da Vitória",
    description: "Saia com a arquitetura completa impressa em dados, prazos e passos para a sua equipe executar.",
  },
];

const companyPillars = [
  {
    icon: Building2,
    title: "Engenharia Limitada para Líderes",
    description: "A ferramenta não é um brinquedo. Foi projetada exclusivamente para empresários e tomadores de decisões da linha de frente.",
  },
  {
    icon: Target,
    title: "Obsessão Pelo Retorno sobre o Tempo",
    description: "Seu cérebro está saturado; a ideia aqui não é ensinar um curso de 4 horas, mas gerar o pilar pragmático em 20 minutos.",
  },
  {
    icon: Handshake,
    title: "Mentor de Bolso de Escala Institucional",
    description: "É como carregar a elite de consultorias do Vale do Silício dentro do seu celular ou escritório, em tempo real.",
  },
];

const securityControls = [
  "Criptografia nativa em fluxos de áudio e websocket",
  "Isolamento transacional por tokenização em memória RAM",
  "Gateway restrito de pagamento bancarizado (Stripe)",
  "Os modelos não treinam usando os dados sensíveis da sua reunião",
];

const contactChannels = [
  {
    icon: Mail,
    title: "Vendas Corporativas",
    value: "executivo@hivemind.ai",
    href: "mailto:executivo@hivemind.ai",
  },
  {
    icon: PhoneCall,
    title: "Emergência B2B",
    value: "+55 (11) 99999-0000",
    href: "https://wa.me/5511999990000",
  },
  {
    icon: CalendarCheck2,
    title: "Investimento & Parceria",
    value: "Agendar Demonstração VIP",
    href: "/register",
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
            className="inline-flex items-center gap-2 bg-linear-to-r from-[#d4af37]/10 to-[#b08d24]/10 border border-[#d4af37]/20 rounded-full px-6 py-2.5 mb-10 backdrop-blur-md shadow-[0_0_20px_rgba(212,175,55,0.1)]"
          >
            <Sparkles className="w-4 h-4 text-[#d4af37]" />
            <span className="text-xs font-black uppercase tracking-[0.2em] text-[#d4af37]">
              Decisões solitárias custam caro. Mude o jogo hoje.
            </span>
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.2 }}
            className="text-6xl sm:text-7xl lg:text-8xl font-black tracking-tighter mb-8 leading-[1.0] uppercase"
          >
            O SEU CONSELHO DE<br />
            <span className="bg-linear-to-r from-[#d4af37] via-[#f0dfa0] to-[#b08d24] bg-clip-text text-transparent italic tracking-normal">ELITE IMPLACÁVEL.</span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.4 }}
            className="text-lg sm:text-xl text-gray-300 max-w-4xl mx-auto mb-10 leading-relaxed font-semibold italic"
          >
            Acabe agora mesmo com a insegurança de decidir o futuro do seu negócio sozinho.
            Entre na sala de comando. Deixe 5 Inteligências Artificiais avaliarem, 
            despedaçarem suas dúvidas e construírem um{" "}
            <span className="text-white border-b-2 border-[#d4af37]/60 px-1 mx-1">Plano de Execução Blindado</span> 
            em tempo real com você.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.6 }}
            className="flex flex-col sm:flex-row items-center justify-center gap-6"
          >
            <Link 
              href="/register" 
              className="group relative px-10 py-5 bg-linear-to-r from-[#b08d24] to-[#d4af37] rounded-2xl shadow-[0_0_40px_rgba(212,175,55,0.25)] hover:shadow-[0_0_60px_rgba(212,175,55,0.5)] transition-all duration-500 transform hover:-translate-y-1"
            >
              <div className="flex items-center gap-3">
                <span className="text-xl font-black text-[#030712] uppercase tracking-tighter">Convocar Comitê Agora</span>
                <ArrowRight className="w-6 h-6 text-[#030712] group-hover:translate-x-1 transition-transform" />
              </div>
            </Link>
            
            <Link 
              href="#how-it-works" 
              className="px-10 py-5 rounded-2xl bg-white/5 border border-white/10 text-lg font-bold text-gray-300 hover:text-white hover:bg-white/10 transition-all backdrop-blur-md"
            >
              Entender a Estratégia Mestra
            </Link>
          </motion.div>

          {/* Carrossel NLP */}
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1, delay: 0.8 }}
          >
            <PersuasionCarousel />
          </motion.div>

          {/* Pentaptych Elite Preview */}
          <motion.div
            initial={{ opacity: 0, y: 60 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1, delay: 1 }}
            className="mt-20 max-w-5xl mx-auto relative group"
          >
            <div className="absolute -inset-1 bg-linear-to-r from-[#d4af37]/20 via-transparent to-[#b08d24]/20 rounded-[40px] blur-2xl opacity-50 group-hover:opacity-100 transition-opacity duration-1000" />
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
                    className={`relative aspect-3/5 overflow-hidden group/agent transition-all duration-500 ${
                      i === 2 ? "scale-105 z-10" : "scale-100"
                    }`}
                  >
                    <div className={`absolute inset-0 bg-linear-to-br ${spec.color} opacity-20`} />
                    {i === 2 && (
                      <div className="absolute -inset-px bg-linear-to-br from-[#d4af37] via-[#f0dfa0] to-[#b08d24] rounded-sm opacity-60 animate-pulse z-0" />
                    )}
                    <div className="absolute inset-0 bg-[#030712]/60 backdrop-blur-[2px]" />
                    <div className="absolute inset-0 flex flex-col items-center justify-center p-2 text-center">
                      <div className={`w-12 h-12 rounded-full flex items-center justify-center bg-linear-to-br ${spec.color} shadow-2xl mb-3 ${i === 2 ? "ring-2 ring-[#d4af37]/50 ring-offset-2 ring-offset-[#030712]" : ""}`}>
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
      <section className="py-20 px-4 mt-8">
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
              className="text-4xl sm:text-5xl font-black mb-6 uppercase tracking-tight"
            >
              Mentes Inflexíveis para um <span className="gradient-text">Lucro Certo</span>
            </motion.h2>
            <motion.p
              variants={fadeUp}
              custom={1}
              className="text-gray-400 max-w-2xl mx-auto font-medium"
            >
              Longe do "papo motivacional". Aqui o sistema confronta fatos, avalia os dados 
              e diz duramente o que falta para seu dinheiro não entrar em risco.
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
                className="glass-card p-6 border border-white/10 hover:border-white/20 transition-all hover:-translate-y-1 bg-black/40"
              >
                <div
                  className={`w-14 h-14 rounded-2xl bg-linear-to-br ${spec.color} flex items-center justify-center mb-5 shadow-lg`}
                >
                  <spec.icon className="w-7 h-7 text-white" />
                </div>
                <h3 className="text-xl font-black uppercase mb-3 text-white">{spec.name}</h3>
                <p className="text-sm text-gray-400 font-medium leading-relaxed">
                  {spec.description}
                </p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="py-24 px-4 bg-[#0a0f1c]/50 border-y border-white/5 relative">
        <div className="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/stardust.png')] opacity-10 pointer-events-none" />
        <div className="max-w-6xl mx-auto relative z-10">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <motion.h2
              variants={fadeUp}
              custom={0}
              className="text-4xl sm:text-5xl font-black mb-4 uppercase tracking-tight"
            >
               Estrutura Projetada para a <span className="gradient-text">Exaustão Estratégica</span>
            </motion.h2>
          </motion.div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-8">
            {features.map((feature, i) => (
              <motion.div
                key={feature.title}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                variants={fadeUp}
                custom={i}
                className="glass-card p-8 border border-white/5 bg-black/20"
              >
                <div className="w-12 h-12 rounded-xl bg-[#d4af37]/10 border border-[#d4af37]/30 flex items-center justify-center mb-6 shadow-[0_0_15px_rgba(212,175,55,0.1)]">
                  <feature.icon className="w-6 h-6 text-[#d4af37]" />
                </div>
                <h3 className="text-xl font-bold mb-3 uppercase tracking-wide">{feature.title}</h3>
                <p className="text-sm text-gray-400 font-medium leading-relaxed">
                  {feature.description}
                </p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing Section */}
      <section id="pricing" className="py-24 px-4 relative">
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-[#d4af37]/5 blur-[150px] pointer-events-none rounded-full" />
        <div className="max-w-5xl mx-auto relative z-10">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <motion.h2
              variants={fadeUp}
              custom={0}
              className="text-4xl sm:text-5xl font-black mb-6 uppercase tracking-tight"
            >
              Transforme Risco de Falística em <span className="gradient-text">Retorno Exponencial</span>
            </motion.h2>
            <motion.p
              variants={fadeUp}
              custom={1}
              className="text-lg text-gray-400 max-w-2xl mx-auto font-medium"
            >
              Um executivo C-Level no Brasil não sai por menos de R$ 200.000 anuais. 
              Aqui estão quatro, à sua espera, por uma mensalidade que você absorveria sem pensar duas vezes no Starbucks.
            </motion.p>
          </motion.div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 lg:gap-12 max-w-4xl mx-auto">
            {plans.map((plan, i) => (
              <motion.div
                key={plan.name}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                variants={fadeUp}
                custom={i}
                className={`glass-card p-10 relative bg-black/60 backdrop-blur-2xl transition-all duration-500 hover:-translate-y-2 ${
                  plan.popular
                    ? "border-[#d4af37] ring-2 ring-[#d4af37]/30 shadow-[0_0_50px_rgba(212,175,55,0.15)]"
                    : "border-white/10"
                }`}
              >
                {plan.popular && (
                  <div className="absolute -top-4 left-1/2 -translate-x-1/2">
                     <div className="bg-[#d4af37] border-2 border-[#030712] text-[#030712] text-xs font-black uppercase tracking-widest px-4 py-1.5 rounded-full shadow-lg">
                       Visão de Sócios (Mais Assinado)
                     </div>
                  </div>
                )}
                <h3 className="text-3xl font-black uppercase tracking-tight mb-2">{plan.name}</h3>
                <p className="text-sm text-[#d4af37] italic font-semibold mb-6 pr-4">
                  "{plan.description}"
                </p>
                <div className="mb-8 border-b border-white/10 pb-8">
                  <span className="text-5xl font-black gradient-text tracking-tighter">
                    {plan.price}
                  </span>
                  <span className="text-sm font-bold uppercase text-gray-500 ml-2">
                    {plan.period}
                  </span>
                </div>
                <ul className="space-y-4 mb-10">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-3">
                      <div className="mt-1 bg-[#d4af37]/20 p-0.5 rounded-full">
                        <Check className="w-3 h-3 text-[#d4af37] shrink-0 font-bold" />
                      </div>
                      <span className="text-gray-300 font-medium">{f}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href="/register"
                  className={`block text-center w-full py-5 rounded-2xl font-black uppercase tracking-widest transition-all ${
                    plan.popular
                      ? "bg-linear-to-r from-[#b08d24] to-[#d4af37] shadow-[0_0_30px_rgba(212,175,55,0.3)] hover:shadow-[0_0_50px_rgba(212,175,55,0.5)] text-[#030712] transform hover:scale-[1.02]"
                      : "bg-white/5 border border-white/10 text-white hover:bg-white/10 hover:border-white/20 transform hover:scale-[1.02]"
                  }`}
                >
                  {plan.cta}
                </Link>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section Final */}
      <section className="py-28 px-4 bg-linear-to-b from-transparent to-[#0a0f1c]/80 border-t border-white/5">
        <div className="max-w-4xl mx-auto text-center">
          <motion.div
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
          >
            <motion.div 
               variants={fadeUp} custom={0} 
               className="w-20 h-20 mx-auto rounded-full bg-[#d4af37]/10 flex items-center justify-center border border-[#d4af37]/20 mb-8 shadow-[0_0_40px_rgba(212,175,55,0.2)]"
            >
               <Target className="w-10 h-10 text-[#d4af37]" />
            </motion.div>

            <motion.h2
              variants={fadeUp}
              custom={1}
              className="text-5xl sm:text-6xl font-black mb-6 uppercase tracking-tighter leading-[1.0]"
            >
              É o fim do amadorismo. <br className="hidden sm:block"/>
              A <span className="gradient-text italic">Sua Vez</span> chegou.
            </motion.h2>
            <motion.p
              variants={fadeUp}
              custom={2}
              className="text-xl text-gray-400 mb-10 max-w-2xl mx-auto font-medium"
            >
              Não permita que o mercado decida qual erro irá quebrar sua empresa. Corrija o rumo hoje, de trás das cortinas cerradas de um conselho bilionário virtual.
            </motion.p>
            <motion.div variants={fadeUp} custom={3}>
              <Link
                href="/register"
                className="group relative inline-flex items-center gap-3 px-12 py-5 bg-linear-to-r from-[#b08d24] to-[#d4af37] rounded-full shadow-[0_0_40px_rgba(212,175,55,0.3)] hover:shadow-[0_0_60px_rgba(212,175,55,0.6)] transition-all duration-500 transform hover:scale-[1.03]"
              >
                <span className="text-xl font-black text-[#030712] uppercase tracking-tighter">Eu Vou Blindar Minha Empresa</span>
                <Flame className="w-6 h-6 text-[#030712] relative z-10" />
              </Link>
              <p className="mt-5 text-sm text-gray-500 uppercase tracking-widest font-black">Testado. Incisivo. Mortal para Concorrentes.</p>
            </motion.div>
          </motion.div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/5 py-16 px-4 bg-[#010204]">
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-col md:flex-row items-center justify-between gap-12">
            <div className="flex flex-col items-center md:items-start gap-4">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 p-1.5 rounded-xl bg-[#0a0a0f] border border-[#d4af37]/30 shadow-[0_0_15px_rgba(212,175,55,0.15)] flex items-center justify-center">
                  <Image src="/logo-icon.svg?v=2" alt="Hive Mind" width={40} height={40} className="w-full h-full object-contain" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
                </div>
                <span className="text-3xl font-black bg-linear-to-r from-[#d4af37] via-[#f0dfa0] to-[#b08d24] bg-clip-text text-transparent uppercase tracking-tighter">HIVE MIND</span>
              </div>
              <p className="text-sm text-gray-600 font-medium max-w-sm text-center md:text-left italic">
                A tecnologia que aposenta achismos na liderança e engessa o erro corporativo como item de museu.
              </p>
            </div>
            
            <div className="flex gap-16">
               <div className="flex flex-col gap-3">
                  <span className="text-[10px] font-black uppercase tracking-[0.3em] text-[#d4af37] mb-2">Engenharia</span>
                  <Link href="#features" className="text-sm font-semibold text-gray-500 hover:text-white transition-colors">Vantagens Matemáticas</Link>
                  <Link href="#pricing" className="text-sm font-semibold text-gray-500 hover:text-white transition-colors">Custo Implacável</Link>
               </div>
               <div className="flex flex-col gap-3">
                  <span className="text-[10px] font-black uppercase tracking-[0.3em] text-[#d4af37] mb-2">Companhia</span>
                  <a href="mailto:executivo@hivemind.ai" className="text-sm font-semibold text-gray-500 hover:text-white transition-colors">Executivo B2B</a>
                  <Link href="/terms-of-service" className="text-sm font-semibold text-gray-500 hover:text-white transition-colors">Privacidade Nível Militar</Link>
               </div>
            </div>
          </div>
          
          <div className="mt-20 pt-8 border-t border-white/5 flex flex-col items-center justify-center gap-2">
            <p className="text-[10px] text-gray-600 uppercase font-black tracking-[0.2em]">
               2026 Hive Mind Corp. Todos os direitos reservados.
            </p>
            <p className="text-[9px] text-gray-800 font-bold tracking-widest text-center mt-2">
               O mercado não perdoa líderes indecisos. Seja rápido.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
