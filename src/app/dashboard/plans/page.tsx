"use client";

import { motion } from "framer-motion";
import { ThemeToggle } from "@/components/theme-toggle";
import Link from "next/link";
import { useSession, signOut } from "next-auth/react";
import { useRouter, usePathname } from "next/navigation";
import {
  Brain,
  Plus,
  FileText,
  CreditCard,
  LogOut,
  Download,
  Video,
  LayoutDashboard,
  Loader2,
  FolderOpen,
  Menu,
  X,
  Calendar,
} from "lucide-react";
import { useState, useEffect } from "react";

type Plan = {
  id: string;
  projectTitle: string;
  projectId: string;
  sessionId: string;
  pdfUrl: string | null;
  hasMarkdown: boolean;
  generatedAt: string;
};

export default function PlansPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, router]);

  useEffect(() => {
    if (status === "authenticated" && session?.user?.id) {
      fetchPlans();
    }
  }, [status, session]);

  const fetchPlans = async () => {
    try {
      setLoading(true);
      const res = await fetch(`/api/plans?userId=${(session?.user as any)?.id}`);
      if (res.ok) {
        const data = await res.json();
        setPlans(data.plans);
      }
    } catch (err) {
      console.error("Erro ao carregar planos:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    setLoggingOut(true);
    await signOut({ callbackUrl: "/login" });
  };

  if (status === "loading" || (status === "authenticated" && loading)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-950">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-r from-[#d4af37] to-[#b08d24] flex items-center justify-center">
            <FileText className="w-6 h-6 text-white animate-pulse" />
          </div>
          <div className="flex items-center gap-2 text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            Carregando planos...
          </div>
        </motion.div>
      </div>
    );
  }

  if (status === "unauthenticated") return null;

  const userName = session?.user?.name || "Usuário";
  const userEmail = session?.user?.email || "";
  const userInitial = userName.charAt(0).toUpperCase();

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
            <div className="w-10 h-10 rounded-lg bg-[#0a0a0f] border border-[#d4af37]/30 flex items-center justify-center">
              <img src="/logo-icon.svg" alt="Hive Mind" className="w-12 h-12" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
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
                <h1 className="text-xl font-bold">Planos de Execução</h1>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Documentos gerados pelas suas mentorias
                </p>
              </div>
            </div>
            <ThemeToggle />
          </div>
        </header>

        <div className="p-6">
          {plans.length === 0 ? (
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="glass-card p-12 text-center">
              <div className="w-16 h-16 rounded-2xl bg-gray-100 dark:bg-white/5 flex items-center justify-center mx-auto mb-4">
                <FolderOpen className="w-8 h-8 text-gray-400" />
              </div>
              <h3 className="text-lg font-semibold mb-2">Nenhum plano gerado ainda</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-6 max-w-sm mx-auto">
                Os planos de execução são gerados automaticamente ao final de cada sessão de mentoria.
              </p>
              <Link href="/dashboard" className="btn-primary inline-flex items-center gap-2">
                <Plus className="w-4 h-4" />
                Iniciar uma Mentoria
              </Link>
            </motion.div>
          ) : (
            <div className="space-y-3">
              {plans.map((plan, i) => (
                <motion.div
                  key={plan.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className="glass-card p-5 flex items-center gap-4"
                >
                  <div className="w-11 h-11 rounded-xl bg-gradient-to-r from-emerald-500/10 to-teal-500/10 border border-emerald-500/20 flex items-center justify-center flex-shrink-0">
                    <FileText className="w-5 h-5 text-emerald-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-sm truncate">{plan.projectTitle}</h3>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-1">
                        <Calendar className="w-3 h-3" />
                        {plan.generatedAt}
                      </span>
                    </div>
                  </div>
                  {plan.pdfUrl && (
                    <a
                      href={plan.pdfUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn-primary text-xs px-4 py-2 flex items-center gap-1.5 flex-shrink-0"
                    >
                      <Download className="w-3.5 h-3.5" />
                      Baixar PDF
                    </a>
                  )}
                  {!plan.pdfUrl && plan.hasMarkdown && (
                    <span className="text-xs px-3 py-1.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 flex-shrink-0">
                      Disponível online
                    </span>
                  )}
                </motion.div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
