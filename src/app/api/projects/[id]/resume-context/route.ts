import { NextRequest, NextResponse } from "next/server";
import { and, asc, desc, eq, inArray, isNotNull } from "drizzle-orm";
import { db } from "@/lib/db";
import { mentoringSessions, projects, users, executionPlans } from "@/lib/db/schema";
import { auth } from "@/auth";

// Secret compartilhado entre o worker Python e o Next.js para chamadas server-to-server.
// Definido em .env como INTERNAL_API_SECRET. Se não definido, chamadas internas serão bloqueadas.
const INTERNAL_API_SECRET = process.env.INTERNAL_API_SECRET || "";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  try {
    // SEGURANÇA: Validação híbrida (browser autenticado OU worker interno).
    const session = await auth();
    const internalSecret = _request.headers.get("x-internal-secret");

    if (!session?.user?.id && internalSecret !== INTERNAL_API_SECRET) {
      return NextResponse.json(
        { error: "Não autenticado." },
        { status: 401 }
      );
    }

    const [project] = await db
      .select({
        projectId: projects.id,
        projectTitle: projects.title,
        projectDescription: projects.description,
        userName: users.name,
        userId: projects.userId,
      })
      .from(projects)
      .innerJoin(users, eq(projects.userId, users.id))
      .where(eq(projects.id, id))
      .limit(1);

    if (!project) {
      return NextResponse.json({ error: "Projeto não encontrado" }, { status: 404 });
    }

    // SEGURANÇA: Se é um browser autenticado, verificar que o projeto pertence ao usuário.
    if (session?.user?.id && project.userId !== session.user.id) {
      return NextResponse.json({ error: "Acesso negado." }, { status: 403 });
    }

    // Busca TODAS as sessões com transcript (ordenadas da mais antiga → mais recente)
    // para montar o Histórico Mestre da mentoria com contexto completo.
    const allSessionsWithTranscript = await db
      .select({
        sessionId: mentoringSessions.id,
        status: mentoringSessions.status,
        startedAt: mentoringSessions.startedAt,
        endedAt: mentoringSessions.endedAt,
        transcript: mentoringSessions.transcript,
      })
      .from(mentoringSessions)
      .where(
        and(
          eq(mentoringSessions.projectId, id),
          isNotNull(mentoringSessions.transcript),
        ),
      )
      .orderBy(asc(mentoringSessions.startedAt));

    // Concatena todos os transcripts em um Histórico Mestre único
    let lastSessionWithTranscript: typeof allSessionsWithTranscript[0] | null = null;
    if (allSessionsWithTranscript.length > 0) {
      const mergedTranscript = allSessionsWithTranscript
        .map((s) => s.transcript)
        .filter(Boolean)
        .join("\n\n");
      // Usa os metadados da sessão mais recente como envelope
      const latest = allSessionsWithTranscript[allSessionsWithTranscript.length - 1];
      lastSessionWithTranscript = {
        ...latest,
        transcript: mergedTranscript,
      };
    }

    // Buscar TODOS os documentos gerados pelo Marco nas sessões deste projeto
    const projectSessions = await db.select({ id: mentoringSessions.id }).from(mentoringSessions).where(eq(mentoringSessions.projectId, id));
    const sessionIds = projectSessions.map(s => s.id);
    
    let generatedDocs: any[] = [];
    if (sessionIds.length > 0) {
      generatedDocs = await db.select({
        docType: executionPlans.docType,
        title: executionPlans.title,
        markdownContent: executionPlans.markdownContent,
        generatedAt: executionPlans.generatedAt
      })
      .from(executionPlans)
      .where(inArray(executionPlans.sessionId, sessionIds))
      .orderBy(desc(executionPlans.generatedAt));
    }

    return NextResponse.json({
      project,
      lastSession: lastSessionWithTranscript ?? null,
      generatedDocs,
    });
  } catch (error) {
    console.error("Erro ao buscar contexto de retomada:", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  try {
    // SEGURANÇA: Validação híbrida (browser autenticado OU worker interno).
    const session = await auth();
    const internalSecret = request.headers.get("x-internal-secret");

    if (!session?.user?.id && internalSecret !== INTERNAL_API_SECRET) {
      return NextResponse.json(
        { error: "Não autenticado." },
        { status: 401 }
      );
    }

    // SEGURANÇA: Se é browser autenticado, verificar ownership do projeto.
    if (session?.user?.id) {
      const [proj] = await db
        .select({ userId: projects.userId })
        .from(projects)
        .where(eq(projects.id, id))
        .limit(1);
      if (!proj || proj.userId !== session.user.id) {
        return NextResponse.json({ error: "Acesso negado." }, { status: 403 });
      }
    }

    const { transcript } = await request.json();

    if (typeof transcript !== "string" || !transcript.trim()) {
      return NextResponse.json({ error: "transcript é obrigatório" }, { status: 400 });
    }

    const [activeSession] = await db
      .select({ id: mentoringSessions.id })
      .from(mentoringSessions)
      .where(
        and(
          eq(mentoringSessions.projectId, id),
          eq(mentoringSessions.status, "active"),
        ),
      )
      .orderBy(desc(mentoringSessions.startedAt))
      .limit(1);

    const targetSession =
      activeSession ??
      (
        await db
          .select({ id: mentoringSessions.id })
          .from(mentoringSessions)
          .where(eq(mentoringSessions.projectId, id))
          .orderBy(desc(mentoringSessions.startedAt))
          .limit(1)
      )[0];

    if (!targetSession) {
      return NextResponse.json({ error: "Sessão não encontrada para snapshot" }, { status: 404 });
    }

    await db
      .update(mentoringSessions)
      .set({ transcript })
      .where(eq(mentoringSessions.id, targetSession.id));

    return NextResponse.json({ success: true, sessionId: targetSession.id });
  } catch (error) {
    console.error("Erro ao salvar snapshot de sessão:", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }
}
