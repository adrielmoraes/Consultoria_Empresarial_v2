import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { projects, users } from "@/lib/db/schema";
import { eq } from "drizzle-orm";
import { auth } from "@/auth";
import { z } from "zod";

// ─── Schemas de validação ────────────────────────────────────────────────────

const createProjectSchema = z.object({
  title: z.string().min(1, "Título é obrigatório").max(200, "Título muito longo"),
  description: z.string().max(2000, "Descrição muito longa").optional(),
});

const listProjectsSchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  limit: z.coerce.number().int().min(1).max(100).default(20),
});

// ─── Campos seguros para retornar ao cliente ──────────────────────────────────
// Evita vazar colunas internas, tokens, dados sensíveis que possam existir
// na tabela hoje ou no futuro.

type SafeProject = {
  id: string;
  title: string;
  description: string | null;
  status: string;
  createdAt: Date;
  updatedAt: Date;
};

function toSafeProject(project: typeof projects.$inferSelect): SafeProject {
  return {
    id: project.id,
    title: project.title,
    description: project.description ?? null,
    status: project.status,
    createdAt: project.createdAt,
    updatedAt: project.updatedAt,
  };
}

// ─── POST /api/projects — Criar novo projeto ──────────────────────────────────

export async function POST(request: NextRequest) {
  try {
    // CORREÇÃO P1: autenticação via sessão do servidor.
    // O userId NUNCA vem do body — vem da sessão autenticada.
    // Isso elimina o IDOR: um usuário só pode criar projetos para si mesmo.
    const session = await auth();

    if (!session?.user?.id) {
      return NextResponse.json(
        { error: "Não autenticado. Faça login para continuar." },
        { status: 401 }
      );
    }

    const userId = session.user.id;

    // Validação e sanitização do body com Zod.
    // Garante tipos corretos, limites de tamanho e rejeita campos inesperados.
    const body = await request.json();
    const parsed = createProjectSchema.safeParse(body);

    if (!parsed.success) {
      return NextResponse.json(
        { error: "Dados inválidos", details: parsed.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const { title, description } = parsed.data;

    // CORREÇÃO P2: tudo dentro de uma transação atômica com SELECT FOR UPDATE.
    //
    // Problema original: duas queries independentes (INSERT + UPDATE) criam
    // uma race condition — dois requests simultâneos leem credits=1, ambos
    // passam na checagem e ambos debitam, permitindo criar 2 projetos com 1 crédito.
    //
    // Solução: a transação garante atomicidade. O FOR UPDATE bloqueia a linha
    // do usuário até o commit, impedindo leituras sujas de outros requests
    // concorrentes para o mesmo userId.
    const project = await db.transaction(async (tx) => {
      // Lê o usuário com lock exclusivo de linha
      const [user] = await tx
        .select()
        .from(users)
        .where(eq(users.id, userId))
        .for("update"); // bloqueia a linha até o fim da transação

      if (!user) {
        // Não deveria acontecer se a sessão é válida, mas tratamos defensivamente
        throw new Error("USER_NOT_FOUND");
      }

      // Verifica créditos dentro da transação, com dados garantidamente frescos
      const hasCredits = (user.credits ?? 0) > 0;
      const hasActiveSubscription = user.subscriptionStatus === "active";

      if (!hasCredits && !hasActiveSubscription) {
        throw new Error("NO_CREDITS");
      }

      // Cria o projeto
      const [newProject] = await tx
        .insert(projects)
        .values({
          userId,
          title,
          description,
          status: "pending",
        })
        .returning();

      // Debita o crédito — só executado se o INSERT acima teve sucesso
      // e apenas para usuários sem assinatura ativa
      if (!hasActiveSubscription) {
        await tx
          .update(users)
          .set({
            credits: Math.max(0, (user.credits ?? 0) - 1),
            updatedAt: new Date(),
          })
          .where(eq(users.id, userId));
      }

      return newProject;
    });

    // CORREÇÃO P5: retorna apenas os campos necessários ao cliente,
    // nunca o objeto completo do banco.
    return NextResponse.json({ project: toSafeProject(project) }, { status: 201 });

  } catch (error) {
    // Trata erros de negócio lançados dentro da transação
    if (error instanceof Error) {
      if (error.message === "USER_NOT_FOUND") {
        return NextResponse.json(
          { error: "Usuário não encontrado." },
          { status: 404 }
        );
      }
      if (error.message === "NO_CREDITS") {
        return NextResponse.json(
          { error: "Sem créditos disponíveis. Adquira um plano para continuar." },
          { status: 403 }
        );
      }
    }

    console.error("[POST /api/projects] Erro inesperado:", error);
    return NextResponse.json({ error: "Erro interno." }, { status: 500 });
  }
}

// ─── GET /api/projects — Listar projetos do usuário autenticado ───────────────

export async function GET(request: NextRequest) {
  try {
    // CORREÇÃO P3: mesmo problema de IDOR do POST.
    // O userId original vinha da query string — qualquer um podia listar
    // os projetos de qualquer userId. Agora vem exclusivamente da sessão.
    const session = await auth();

    if (!session?.user?.id) {
      return NextResponse.json(
        { error: "Não autenticado. Faça login para continuar." },
        { status: 401 }
      );
    }

    const userId = session.user.id;

    // CORREÇÃO P4: paginação obrigatória.
    // Sem paginação, um usuário com muitos projetos causa queries pesadas
    // e payloads gigantes. Agora aceitamos ?page=1&limit=20 (padrão).
    const { searchParams } = request.nextUrl;
    const paginationParsed = listProjectsSchema.safeParse({
      page: searchParams.get("page"),
      limit: searchParams.get("limit"),
    });

    if (!paginationParsed.success) {
      return NextResponse.json(
        { error: "Parâmetros de paginação inválidos." },
        { status: 400 }
      );
    }

    const { page, limit } = paginationParsed.data;
    const offset = (page - 1) * limit;

    const userProjects = await db
      .select()
      .from(projects)
      .where(eq(projects.userId, userId))
      .orderBy(projects.createdAt)
      .limit(limit)
      .offset(offset);

    // CORREÇÃO P5: projetar apenas campos seguros na listagem também
    return NextResponse.json({
      projects: userProjects.map(toSafeProject),
      pagination: {
        page,
        limit,
        // hasMore indica ao cliente se deve buscar a próxima página
        hasMore: userProjects.length === limit,
      },
    });

  } catch (error) {
    console.error("[GET /api/projects] Erro inesperado:", error);
    return NextResponse.json({ error: "Erro interno." }, { status: 500 });
  }
}