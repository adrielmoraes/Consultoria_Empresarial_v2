import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { executionPlans, mentoringSessions, projects, users } from "@/lib/db/schema";
import { eq } from "drizzle-orm";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  try {
    const { sessionId } = await params;

    if (!sessionId) {
      return NextResponse.json({ error: "sessionId é obrigatório" }, { status: 400 });
    }

    const session = await db.query.mentoringSessions.findFirst({
      where: eq(mentoringSessions.id, sessionId),
      with: {
        project: {
          with: {
            user: true,
          },
        },
      },
    });

    if (!session) {
      return NextResponse.json({ error: "Sessão não encontrada" }, { status: 404 });
    }

    const plan = await db.query.executionPlans.findFirst({
      where: eq(executionPlans.sessionId, sessionId),
    });

    if (!plan) {
      return NextResponse.json({ error: "Plano não encontrado" }, { status: 404 });
    }

    return NextResponse.json({
      plan: {
        id: plan.id,
        markdownContent: plan.markdownContent,
        generatedAt: plan.generatedAt,
      },
      session: {
        id: session.id,
        startedAt: session.startedAt,
        endedAt: session.endedAt,
      },
      project: {
        id: session.project.id,
        title: session.project.title,
      },
      user: {
        name: session.project.user?.name || "Usuário",
      },
    });
  } catch (error) {
    console.error("Erro ao buscar plano:", error);
    return NextResponse.json({ error: "Erro ao buscar plano" }, { status: 500 });
  }
}
