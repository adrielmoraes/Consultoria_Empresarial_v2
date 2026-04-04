"use client";

import { motion } from "framer-motion";
import { ThemeToggle } from "@/components/theme-toggle";
import { NewProjectModal } from "@/components/new-project-modal";
import Link from "next/link";
import { useSession, signOut } from "next-auth/react";
import { useRouter, usePathname } from "next/navigation";
import {
  Brain,
  Plus,
  FileText,
  Clock,
  CreditCard,
  LogOut,
  Download,
  ChevronRight,
  Sparkles,
  Video,
  LayoutDashboard,
  ArrowRight,
  Loader2,
  FolderOpen,
  Menu,
  X,
} from "lucide-react";
import { useState, useEffect } from "react";

type Project = {
  id: string;
  title: string;
  description: string | null;
  status: "pending" | "in_progress" | "completed";
  createdAt: string;
  hasPdf: boolean;
};

type DashboardData = {
  user: {
    id: string;
    name: string;
    email: string;
    credits: number | null;
    subscriptionStatus: string | null;
    createdAt: string;
  };
  projects: Project[];
  stats: {
    totalProjects: number;
    totalSessions: number;
    totalPlans: number;
    totalTime: string;
    credits: number;
  };
};

const statusMap = {
  pending: {
    label: "Pendente",
    color: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  },
  in_progress: {
    label: "Em andamento",
    color: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  },
  completed: {
    label: "Concluído",
    color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  },
};

export default function DashboardPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [dashData, setDashData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showNewProject, setShowNewProject] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  // Proteção de rota
  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status]);

  // Buscar dados do dashboard (apenas quando autenticação é confirmada)
  useEffect(() => {
    if (status === "authenticated" && session?.user?.id) {
      fetchDashboard();
    }
  }, [status]);

  const fetchDashboard = async () => {
    try {
      setLoading(true);
      const res = await fetch(`/api/dashboard?userId=${session?.user?.id}`);
      if (res.ok) {
        const data = await res.json();
        setDashData(data);
      }
    } catch (err) {
      console.error("Erro ao carregar dashboard:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    setLoggingOut(true);
    await signOut({ callbackUrl: "/login" });
  };

  // Loading state
  if (status === "loading" || (status === "authenticated" && loading)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-950">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex flex-col items-center gap-4"
        >
          <div className="w-14 h-14 rounded-xl bg-[#0a0a0f] border border-[#d4af37]/30 flex items-center justify-center">
            <img src="/logo-icon.svg" alt="Hive Mind" className="w-10 h-10 animate-pulse" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
          </div>
          <div className="flex items-center gap-2 text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" />
            Carregando dashboard...
          </div>
        </motion.div>
      </div>
    );
  }

  if (status === "unauthenticated") return null;

  const userName = dashData?.user?.name || session?.user?.name || "Usuário";
  const userEmail = dashData?.user?.email || session?.user?.email || "";
  const userInitial = userName.charAt(0).toUpperCase();
  const userId = (session?.user as any)?.id || "";

  const stats = dashData?.stats || {
    totalProjects: 0,
    totalSessions: 0,
    totalPlans: 0,
    totalTime: "0m",
    credits: 0,
  };

  const projects = dashData?.projects || [];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      {/* Mobile Sidebar Overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed top-0 left-0 bottom-0 w-64 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-white/5 flex flex-col z-50 transition-transform duration-300 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        }`}
      >
        {/* Logo */}
        <div className="p-6 border-b border-gray-200 dark:border-white/5 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <div className="w-10 h-10 rounded-lg bg-[#0a0a0f] border border-[#d4af37]/30 flex items-center justify-center">
              <img src="/logo-icon.svg" alt="Hive Mind" className="w-7 h-7" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
            </div>
            <span className="text-lg font-bold gradient-text">Hive Mind</span>
          </Link>
          <button
            className="lg:hidden text-gray-400 hover:text-white"
            onClick={() => setSidebarOpen(false)}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-4 space-y-1">
          {[
            { href: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
            { href: "/dashboard/plans", icon: FileText, label: "Planos de Execução" },
            { href: "/dashboard/subscription", icon: CreditCard, label: "Assinatura" },
          ].map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl text-sm transition-colors ${
                  isActive
                    ? "bg-[#d4af37]/10 text-[#d4af37] dark:text-[#e6c86a] font-medium"
                    : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-white/5"
                }`}
              >
                <item.icon className="w-5 h-5" />
                {item.label}
              </Link>
            );
          })}
          <button
            onClick={() => setShowNewProject(true)}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-white/5 text-sm transition-colors"
          >
            <Video className="w-5 h-5" />
            Nova Mentoria
          </button>
        </nav>

        {/* User */}
        <div className="p-4 border-t border-gray-200 dark:border-white/5">
          <div className="flex items-center gap-3 px-4 py-3">
            <div className="w-9 h-9 rounded-full bg-gradient-to-r from-[#d4af37] to-[#b08d24] flex items-center justify-center text-white font-bold text-sm">
              {userInitial}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{userName}</p>
              <p className="text-xs text-gray-500 truncate">{userEmail}</p>
            </div>
            <button
              onClick={handleLogout}
              disabled={loggingOut}
              title="Sair"
              className="text-gray-400 hover:text-red-400 transition-colors disabled:opacity-50"
            >
              {loggingOut ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <LogOut className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="lg:ml-64">
        {/* Top Bar */}
        <header className="sticky top-0 z-30 bg-white/70 dark:bg-gray-950/70 backdrop-blur-xl border-b border-gray-200 dark:border-white/5">
          <div className="flex items-center justify-between px-6 py-4">
            <div className="flex items-center gap-3">
              <button
                className="lg:hidden text-gray-500 hover:text-white"
                onClick={() => setSidebarOpen(true)}
              >
                <Menu className="w-6 h-6" />
              </button>
              <div>
                <h1 className="text-xl font-bold">Dashboard</h1>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Bem-vindo de volta, {userName.split(" ")[0]}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <ThemeToggle />
              <button
                onClick={() => setShowNewProject(true)}
                className="btn-primary flex items-center gap-2 text-sm"
              >
                <Plus className="w-4 h-4" />
                <span className="hidden sm:inline">Nova Mentoria</span>
              </button>
            </div>
          </div>
        </header>

        <div className="p-6 space-y-6">
          {/* Stats Cards */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
          >
            {[
              {
                icon: Video,
                label: "Mentorias Realizadas",
                value: String(stats.totalSessions),
                color: "text-[#d4af37]",
              },
              {
                icon: FileText,
                label: "Planos Gerados",
                value: String(stats.totalPlans),
                color: "text-emerald-400",
              },
              {
                icon: CreditCard,
                label: "Créditos Restantes",
                value: String(stats.credits),
                color: "text-[#e6c86a]",
              },
              {
                icon: Clock,
                label: "Tempo Total",
                value: stats.totalTime,
                color: "text-orange-400",
              },
            ].map((stat, i) => (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.1 }}
                className="glass-card p-5"
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-gray-100 dark:bg-white/5 flex items-center justify-center">
                    <stat.icon className={`w-5 h-5 ${stat.color}`} />
                  </div>
                  <div>
                    <p className="text-2xl font-bold">{stat.value}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      {stat.label}
                    </p>
                  </div>
                </div>
              </motion.div>
            ))}
          </motion.div>

          {/* Quick Action */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="glass-card p-6 bg-gradient-to-r from-[#d4af37]/5 to-[#b08d24]/5 border-[#d4af37]/20"
          >
            <div className="flex flex-col sm:flex-row items-center gap-4">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-r from-[#d4af37] to-[#b08d24] flex items-center justify-center flex-shrink-0">
                <Sparkles className="w-7 h-7 text-white" />
              </div>
              <div className="flex-1 text-center sm:text-left">
                <h3 className="text-lg font-bold mb-1">Iniciar Nova Mentoria</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Descreva seu projeto e entre em uma sala com 5 especialistas de IA.
                </p>
              </div>
              <button
                onClick={() => setShowNewProject(true)}
                className="btn-primary flex items-center gap-2 flex-shrink-0"
              >
                Começar <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </motion.div>

          {/* Projects List */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.4 }}
          >
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold">Seus Projetos</h2>
              {projects.length > 0 && (
                <span className="text-sm text-gray-500 dark:text-gray-400">
                  {projects.length} projeto{projects.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>

            {projects.length === 0 ? (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="glass-card p-12 text-center"
              >
                <div className="w-16 h-16 rounded-2xl bg-gray-100 dark:bg-white/5 flex items-center justify-center mx-auto mb-4">
                  <FolderOpen className="w-8 h-8 text-gray-400" />
                </div>
                <h3 className="text-lg font-semibold mb-2">
                  Nenhum projeto ainda
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-6 max-w-sm mx-auto">
                  Comece sua primeira mentoria e tenha acesso a um painel com 5
                  especialistas de IA para alavancar seu projeto.
                </p>
                <button
                  onClick={() => setShowNewProject(true)}
                  className="btn-primary inline-flex items-center gap-2"
                >
                  <Sparkles className="w-4 h-4" />
                  Criar Primeiro Projeto
                </button>
              </motion.div>
            ) : (
              <div className="space-y-3">
                {projects.map((project, i) => (
                  <motion.div
                    key={project.id}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.5 + i * 0.1 }}
                  >
                    <Link
                      href={`/mentorship/${project.id}`}
                      className="glass-card p-5 flex items-center gap-4 cursor-pointer group block"
                    >
                      <div className="w-11 h-11 rounded-xl bg-gradient-to-r from-[#d4af37]/10 to-[#b08d24]/10 border border-[#d4af37]/20 flex items-center justify-center flex-shrink-0 p-1.5">
                        <img src="/logo-icon.svg" alt="Project" className="w-7 h-7" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="font-semibold text-sm truncate">
                          {project.title}
                        </h3>
                        <div className="flex items-center gap-3 mt-1">
                          <span
                            className={`text-xs px-2 py-0.5 rounded-full border ${
                              statusMap[project.status]?.color ||
                              statusMap.pending.color
                            }`}
                          >
                            {statusMap[project.status]?.label ||
                              statusMap.pending.label}
                          </span>
                          <span className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {project.createdAt}
                          </span>
                        </div>
                      </div>
                      {project.hasPdf && (
                        <button
                          className="btn-secondary text-xs px-3 py-2 flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Download className="w-3.5 h-3.5" />
                          PDF
                        </button>
                      )}
                      <ChevronRight className="w-5 h-5 text-gray-400 group-hover:text-[#d4af37] transition-colors flex-shrink-0" />
                    </Link>
                  </motion.div>
                ))}
              </div>
            )}
          </motion.div>
        </div>
      </main>

      {/* New Project Modal */}
      <NewProjectModal
        isOpen={showNewProject}
        onClose={() => setShowNewProject(false)}
        userId={userId}
      />
    </div>
  );
}
