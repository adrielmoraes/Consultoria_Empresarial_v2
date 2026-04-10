"use client";

import { motion } from "framer-motion";
import { ThemeToggle } from "@/components/theme-toggle";
import Link from "next/link";
import { useSession, signOut } from "next-auth/react";
import { useRouter, usePathname } from "next/navigation";
import {
  FileText,
  CreditCard,
  LogOut,
  LayoutDashboard,
  Loader2,
  Menu,
  X,
  Check,
  Sparkles,
  Zap,
  Crown,
  Star,
} from "lucide-react";
import { useState, useEffect } from "react";

type UserData = {
  credits: number | null;
  subscriptionStatus: string | null;
};

const plans = [
  {
    id: "free",
    name: "Gratuito",
    price: "R$ 0",
    period: "",
    icon: Star,
    gradient: "from-gray-500 to-gray-600",
    borderColor: "border-gray-500/20",
    features: [
      "1 crédito de teste",
      "Mentoria com 5 especialistas IA",
      "12 minutos de mentoria",
      "Plano de execução básico",
    ],
    cta: "Plano Atual",
    disabled: true,
  },
  {
    id: "session",
    name: "Sessão Avulsa",
    price: "R$ 149,90",
    period: "/sessão",
    icon: Zap,
    gradient: "from-[#d4af37] to-[#b08d24]",
    borderColor: "border-[#d4af37]/30",
    popular: true,
    features: [
      "1 mentoria",
      "Mentoria com 5 especialistas IA",
      "Plano de execução completo em PDF",
      "30 minutos de reunião",
    ],
    cta: "Comprar Sessão",
    disabled: false,
  },
  {
    id: "professional",
    name: "Profissional",
    price: "R$ 399,90",
    period: "/mês",
    icon: Crown,
    gradient: "from-amber-500 to-orange-600",
    borderColor: "border-amber-500/30",
    features: [
      "5 mentorias por mês",
      "Mentoria com 5 especialistas IA",
      "Plano de execução completo em PDF",
      "60 minutos por reunião",
      "Suporte prioritário por e-mail",
    ],
    cta: "Assinar Profissional",
    disabled: false,
  },
];

export default function SubscriptionPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [userData, setUserData] = useState<UserData | null>(null);
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [purchasing, setPurchasing] = useState<string | null>(null);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, router]);

  useEffect(() => {
    if (status === "authenticated" && session?.user?.id) {
      fetchUserData();
    }
  }, [status, session]);

  const fetchUserData = async () => {
    try {
      setLoading(true);
      const userId = (session?.user as { id?: string } | undefined)?.id;
      const res = await fetch(`/api/dashboard?userId=${userId ?? ""}`);
      if (res.ok) {
        const data = await res.json();
        setUserData({
          credits: data.user.credits,
          subscriptionStatus: data.user.subscriptionStatus,
        });
      }
    } catch (err) {
      console.error("Erro ao carregar dados:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleSubscribe = async (planId: string) => {
    setPurchasing(planId);
    try {
      const userId = (session?.user as { id?: string } | undefined)?.id;
      if (!userId) {
        throw new Error("Usuário não autenticado");
      }

      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          planId,
          userId,
          userEmail: session?.user?.email ?? undefined,
        }),
      });

      const data = await res.json();
      if (!res.ok || !data.url) {
        throw new Error(data?.error || "Falha ao iniciar checkout");
      }

      window.location.href = data.url;
    } catch (error) {
      console.error("Erro ao iniciar checkout:", error);
      alert("Não foi possível iniciar o checkout. Tente novamente.");
    } finally {
      setPurchasing(null);
    }
  };

  const handleLogout = async () => {
    setLoggingOut(true);
    await signOut({ callbackUrl: "/" });
  };

  if (status === "loading" || (status === "authenticated" && loading)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-950">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-r from-[#d4af37] to-[#b08d24] flex items-center justify-center">
            <CreditCard className="w-6 h-6 text-white animate-pulse" />
          </div>
          <div className="flex items-center gap-2 text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            Carregando assinatura...
          </div>
        </motion.div>
      </div>
    );
  }

  if (status === "unauthenticated") return null;

  const userName = session?.user?.name || "Usuário";
  const userEmail = session?.user?.email || "";
  const userInitial = userName.charAt(0).toUpperCase();
  const currentStatus = userData?.subscriptionStatus || "trial";
  const currentCredits = userData?.credits ?? 0;
  const currentPlanId =
    currentStatus === "active"
      ? "professional"
      : currentCredits > 0
        ? "session"
        : "free";
  const currentPlanName =
    currentPlanId === "professional"
        ? "Profissional"
        : currentPlanId === "session"
          ? "Sessão Avulsa"
          : "Gratuito (Trial)";

  const navItems = [
    { href: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
    { href: "/dashboard/plans", icon: FileText, label: "Planos de Execução" },
    { href: "/dashboard/subscription", icon: CreditCard, label: "Assinatura" },
  ];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      {sidebarOpen && (
        <div className="fixed inset-0 bg-black/50 z-40 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <aside className={`fixed top-0 left-0 bottom-0 w-64 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-white/5 flex flex-col z-50 transition-transform duration-300 ${sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`}>
        <div className="p-6 border-b border-gray-200 dark:border-white/5 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <div className="w-12 h-12 rounded-lg bg-[#0a0a0f] border border-[#d4af37]/30 flex items-center justify-center p-1">
              <img src="/logo-icon.svg?v=2" alt="Hive Mind" className="w-full h-full object-contain" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
            </div>
            <span className="text-lg font-bold gradient-text">Hive Mind</span>
          </Link>
          <button className="lg:hidden text-gray-400 hover:text-white" onClick={() => setSidebarOpen(false)}>
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="flex-1 p-4 space-y-1">
          {navItems.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl text-sm transition-colors ${isActive
                  ? "bg-[#d4af37]/10 text-[#d4af37] dark:text-[#e6c86a] font-medium"
                  : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-white/5"
                  }`}
              >
                <item.icon className="w-5 h-5" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="p-4 border-t border-gray-200 dark:border-white/5">
          <div className="flex items-center gap-3 px-4 py-3">
            <div className="w-9 h-9 rounded-full bg-gradient-to-r from-[#d4af37] to-[#b08d24] flex items-center justify-center text-white font-bold text-sm">
              {userInitial}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{userName}</p>
              <p className="text-xs text-gray-500 truncate">{userEmail}</p>
            </div>
            <button onClick={handleLogout} disabled={loggingOut} title="Sair" className="text-gray-400 hover:text-red-400 transition-colors disabled:opacity-50">
              {loggingOut ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogOut className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="lg:ml-64">
        <header className="sticky top-0 z-30 bg-white/70 dark:bg-gray-950/70 backdrop-blur-xl border-b border-gray-200 dark:border-white/5">
          <div className="flex items-center justify-between px-6 py-4">
            <div className="flex items-center gap-3">
              <button className="lg:hidden text-gray-500 hover:text-white" onClick={() => setSidebarOpen(true)}>
                <Menu className="w-6 h-6" />
              </button>
              <div>
                <h1 className="text-xl font-bold">Assinatura</h1>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Gerencie seu plano e créditos
                </p>
              </div>
            </div>
            <ThemeToggle />
          </div>
        </header>

        <div className="p-6 space-y-6">
          {/* Current Status */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass-card p-6 bg-gradient-to-r from-[#d4af37]/5 to-[#b08d24]/5 border-[#d4af37]/20"
          >
            <div className="flex flex-col sm:flex-row items-center gap-4">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-r from-[#d4af37] to-[#b08d24] flex items-center justify-center flex-shrink-0">
                <Sparkles className="w-7 h-7 text-white" />
              </div>
              <div className="flex-1 text-center sm:text-left">
                <h3 className="text-lg font-bold mb-1">
                  Seu Plano:{" "}
                  <span className="gradient-text capitalize">
                    {currentPlanName}
                  </span>
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Você possui <strong className="text-white">{currentCredits}</strong>{" "}
                  crédito{currentCredits !== 1 ? "s" : ""} restante
                  {currentCredits !== 1 ? "s" : ""}
                </p>
              </div>
            </div>
          </motion.div>

          {/* Plans Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {plans.map((plan, i) => {
              const isCurrentPlan = plan.id === currentPlanId;
              const Icon = plan.icon;
              return (
                <motion.div
                  key={plan.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.1 }}
                  className={`glass-card p-6 relative flex flex-col ${plan.borderColor} ${plan.popular ? "ring-2 ring-[#d4af37]/30" : ""
                    }`}
                >
                  {plan.popular && (
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 bg-gradient-to-r from-[#d4af37] to-[#b08d24] rounded-full text-xs font-bold text-white">
                      Mais Popular
                    </div>
                  )}

                  <div className="flex items-center gap-3 mb-4">
                    <div className={`w-10 h-10 rounded-xl bg-gradient-to-r ${plan.gradient} flex items-center justify-center`}>
                      <Icon className="w-5 h-5 text-white" />
                    </div>
                    <div>
                      <h3 className="font-bold">{plan.name}</h3>
                    </div>
                  </div>

                  <div className="mb-6">
                    <span className="text-3xl font-bold">{plan.price}</span>
                    {plan.period && (
                      <span className="text-sm text-gray-500">{plan.period}</span>
                    )}
                  </div>

                  <ul className="space-y-3 mb-8 flex-1">
                    {plan.features.map((feature) => (
                      <li key={feature} className="flex items-start gap-2 text-sm">
                        <Check className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" />
                        <span className="text-gray-600 dark:text-gray-300">{feature}</span>
                      </li>
                    ))}
                  </ul>

                  <button
                    onClick={() => !isCurrentPlan && !plan.disabled && handleSubscribe(plan.id)}
                    disabled={isCurrentPlan || plan.disabled || purchasing === plan.id}
                    className={`w-full py-3 rounded-xl font-semibold text-sm transition-all flex items-center justify-center gap-2 ${isCurrentPlan
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 cursor-default"
                      : plan.popular
                        ? "btn-primary"
                        : "btn-secondary"
                      } disabled:opacity-60`}
                  >
                    {purchasing === plan.id ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : isCurrentPlan ? (
                      <>
                        <Check className="w-4 h-4" /> Plano Atual
                      </>
                    ) : (
                      plan.cta
                    )}
                  </button>
                </motion.div>
              );
            })}
          </div>
        </div>
      </main>
    </div>
  );
}
