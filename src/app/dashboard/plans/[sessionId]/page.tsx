"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { motion } from "framer-motion";
import Link from "next/link";
import { 
  ArrowLeft, 
  Download, 
  FileText, 
  Loader2, 
  Menu,
  X,
  Calendar,
  LayoutDashboard,
  CreditCard,
  LogOut,
  Printer
} from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";

type PlanData = {
  plan: {
    id: string;
    docTitle: string;
    docType: string;
    pdfUrl: string | null;
    markdownContent: string | null;
    generatedAt: string;
  };
  session: {
    id: string;
    startedAt: string;
    endedAt: string | null;
  };
  project: {
    id: string;
    title: string;
  };
  user: {
    name: string;
  };
};

// Um componente simples para renderizar markdown básico sem dependências externas
const SimpleMarkdown = ({ content }: { content: string }) => {
  if (!content) return null;

  // Processamento básico de quebras de linha e formatações
  const processLine = (line: string, index: number) => {
    // Títulos
    if (line.startsWith('# ')) return <h1 key={index} className="text-3xl font-bold mt-8 mb-4 gradient-text">{line.replace('# ', '')}</h1>;
    if (line.startsWith('## ')) return <h2 key={index} className="text-2xl font-semibold mt-6 mb-3 text-gray-900 dark:text-gray-100">{line.replace('## ', '')}</h2>;
    if (line.startsWith('### ')) return <h3 key={index} className="text-xl font-medium mt-5 mb-2 text-gray-800 dark:text-gray-200">{line.replace('### ', '')}</h3>;
    
    // Listas
    if (line.startsWith('- ') || line.startsWith('* ')) {
      const text = line.substring(2);
      return (
        <li key={index} className="ml-4 mb-1 list-disc text-gray-700 dark:text-gray-300">
          <span dangerouslySetInnerHTML={{ __html: parseBold(text) }} />
        </li>
      );
    }
    
    // Linhas horizontais
    if (line === '---' || line === '***') return <hr key={index} className="my-6 border-gray-200 dark:border-white/10" />;

    // Negrito simples para o texto restante e quebra de linha
    if (line.trim() === '') return <br key={index} />;

    return (
      <p key={index} className="mb-2 text-gray-700 dark:text-gray-300">
        <span dangerouslySetInnerHTML={{ __html: parseBold(line) }} />
      </p>
    );
  };

  const parseBold = (text: string) => {
    // Trata **negrito** e *itálico* de forma bem simples com HTML
    let html = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    return html;
  };

  const lines = content.split('\n');

  return (
    <div className="prose prose-sm sm:prose lg:prose-lg dark:prose-invert max-w-none print:text-black print:prose-p:text-black">
      {lines.map((line, i) => processLine(line, i))}
    </div>
  );
};

export default function PlanViewerPage() {
  const params = useParams();
  const router = useRouter();
  const { data: sessionData, status } = useSession();
  
  const [data, setData] = useState<PlanData | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, router]);

  useEffect(() => {
    if (status === "authenticated" && params?.sessionId) {
      fetchPlan();
    }
  }, [status, params]);

  const fetchPlan = async () => {
    try {
      setLoading(true);
      // Lê planId da query string para buscar o documento específico
      const searchParams = new URLSearchParams(window.location.search);
      const planId = searchParams.get("planId");
      const queryStr = planId 
        ? `format=json&planId=${planId}` 
        : "format=json";
      const res = await fetch(`/api/execution-plan/${params.sessionId}?${queryStr}`);
      if (res.ok) {
        const jsonText = await res.json();
        setData(jsonText);
      } else {
        console.error("Plano não encontrado");
        // router.replace("/dashboard/plans");
      }
    } catch (err) {
      console.error("Erro ao buscar plano:", err);
    } finally {
      setLoading(false);
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
          <Loader2 className="w-8 h-8 animate-spin text-[#d4af37]" />
          <div className="text-gray-500">Carregando plano de execução...</div>
        </motion.div>
      </div>
    );
  }

  if (status === "unauthenticated") return null;

  const handleDownloadPdf = async () => {
    if (!data) return;
    setDownloading(true);
    try {
      // Faz o download do PDF via API (sem sair da aba)
      const res = await fetch(`/api/execution-plan/${data.session.id}?planId=${data.plan.id}`);
      if (!res.ok) throw new Error("Erro ao baixar PDF");
      
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      
      // Nome do arquivo baseado no título do documento
      const docTitle = data.plan.docTitle || "Plano de Execução";
      const safeFileName = docTitle
        .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
        .replace(/[^a-zA-Z0-9\s-]/g, "")
        .replace(/\s+/g, "_")
        .substring(0, 80)
        || "documento";
      a.download = `${safeFileName}.pdf`;
      
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Erro ao baixar PDF:", err);
      // Fallback: usa window.print()
      window.print();
    } finally {
      setDownloading(false);
    }
  };

  const userName = sessionData?.user?.name || "Usuário";
  const userEmail = sessionData?.user?.email || "";
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

      {/* Sidebar - Oculta ao imprimir (print:hidden) */}
      <aside className={`print:hidden fixed top-0 left-0 bottom-0 w-64 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-white/5 flex flex-col z-50 transition-transform duration-300 ${sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}`}>
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
            const isActive = item.href === "/dashboard/plans";
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
      </aside>

      {/* Main Content */}
      <main className="lg:ml-64 print:ml-0">
        {/* Top Header - Oculto ao imprimir */}
        <header className="print:hidden sticky top-0 z-30 bg-white/70 dark:bg-gray-950/70 backdrop-blur-xl border-b border-gray-200 dark:border-white/5">
          <div className="flex items-center justify-between px-6 py-4">
            <div className="flex items-center gap-3">
              <button className="lg:hidden text-gray-500 hover:text-white" onClick={() => setSidebarOpen(true)}>
                <Menu className="w-6 h-6" />
              </button>
              <div className="flex items-center gap-3">
                <Link 
                  href="/dashboard/plans" 
                  className="flex items-center justify-center w-8 h-8 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors"
                >
                  <ArrowLeft className="w-5 h-5" />
                </Link>
                <div>
                  <h1 className="text-xl font-bold">Visualização do Plano</h1>
                </div>
              </div>
            </div>
            <ThemeToggle />
          </div>
        </header>

        <div className="p-4 md:p-8">
          {data ? (
            <motion.div 
              initial={{ opacity: 0, y: 20 }} 
              animate={{ opacity: 1, y: 0 }} 
              className="max-w-4xl mx-auto"
            >
              {/* Header do Documento */}
              <div className="glass-card p-6 md:p-8 mb-6 print:shadow-none print:border-none print:p-0">
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8 print:hidden">
                  <div>
                    <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
                      {data.plan.docTitle}
                    </h2>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                      {data.project.title}
                    </p>
                    <div className="flex items-center gap-2 mt-2 text-sm text-gray-500 dark:text-gray-400">
                      <Calendar className="w-4 h-4" />
                      <span>Gerado em {new Date(data.plan.generatedAt).toLocaleDateString('pt-BR', { 
                        day: '2-digit', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit'
                      })}</span>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-3">
                    {/* Botão para baixar PDF diretamente (sem sair da aba) */}
                    {data.plan.pdfUrl ? (
                      <button 
                        onClick={handleDownloadPdf}
                        disabled={downloading}
                        className="btn-primary px-4 py-2 flex items-center gap-2 text-sm disabled:opacity-50"
                      >
                        {downloading ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Download className="w-4 h-4" />
                        )}
                        {downloading ? "Baixando..." : "Baixar PDF"}
                      </button>
                    ) : (
                      <button 
                        onClick={() => window.print()}
                        className="px-4 py-2 flex items-center gap-2 rounded-lg bg-gray-100 dark:bg-white/5 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-white/10 transition-colors text-sm font-medium"
                      >
                        <Printer className="w-4 h-4" />
                        Imprimir
                      </button>
                    )}
                  </div>
                </div>

                {/* Conteúdo Renderizado do Plano */}
                <div className="bg-white dark:bg-[#0a0a0f] rounded-2xl p-6 md:p-10 border border-gray-100 dark:border-white/5 print:border-none print:p-0">
                  <div className="print:block hidden mb-8 text-center pb-8 border-b border-gray-200">
                    <h1 className="text-3xl font-bold text-black mb-2">{data.plan.docTitle}</h1>
                    <p className="text-gray-500 text-sm mb-1">{data.project.title}</p>
                    <p className="text-gray-600">Gerado por Hive Mind - Mentoria Estratégica</p>
                  </div>
                  
                  {data.plan.markdownContent ? (
                    <SimpleMarkdown content={data.plan.markdownContent} />
                  ) : (
                    <div className="text-center py-12 text-gray-500">
                      O conteúdo deste plano não está disponível em formato de texto.
                      {data.plan.pdfUrl && " Por favor, faça o download do arquivo PDF."}
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          ) : (
            <div className="text-center py-20 text-red-500">
              <p>Plano não encontrado ou erro ao carregar dados.</p>
              <Link href="/dashboard/plans" className="text-blue-500 hover:underline mt-4 inline-block">
                Voltar aos Planos
              </Link>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
