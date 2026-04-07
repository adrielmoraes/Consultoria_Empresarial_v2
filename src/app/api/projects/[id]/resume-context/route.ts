import { NextRequest, NextResponse } from "next/server";
import { and, desc, eq, isNotNull } from "drizzle-orm";
import { db } from "@/lib/db";
import { mentoringSessions, projects, users } from "@/lib/db/schema";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  try {
    const [project] = await db
      .select({
        projectId: projects.id,
        projectTitle: projects.title,
        projectDescription: projects.description,
        userName: users.name,
      })
      .from(projects)
      .innerJoin(users, eq(projects.userId, users.id))
      .where(eq(projects.id, id))
      .limit(1);

    if (!project) {
      return NextResponse.json({ error: "Projeto não encontrado" }, { status: 404 });
    }

    const [lastSessionWithTranscript] = await db
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
      .orderBy(desc(mentoringSessions.startedAt))
      .limit(1);

    return NextResponse.json({
      project,
      lastSession: lastSessionWithTranscript ?? null,
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
