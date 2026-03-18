import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { mentoringSessions, executionPlans, projects } from "@/lib/db/schema";
import { eq } from "drizzle-orm";

export async function POST(request: NextRequest) {
  try {
    const { sessionId, transcript, markdownContent, pdfUrl } = await request.json();

    if (!sessionId) {
      return NextResponse.json({ error: "sessionId é obrigatório" }, { status: 400 });
    }

    // Atualizar sessão como concluída
    const [session] = await db
      .update(mentoringSessions)
      .set({
        status: "completed",
        endedAt: new Date(),
        transcript: transcript || null,
      })
      .where(eq(mentoringSessions.id, sessionId))
      .returning();

    if (!session) {
      return NextResponse.json({ error: "Sessão não encontrada" }, { status: 404 });
    }

    // Criar plano de execução se houver conteúdo
    if (markdownContent || pdfUrl) {
      await db.insert(executionPlans).values({
        sessionId,
        pdfUrl: pdfUrl || null,
        markdownContent: markdownContent || null,
      });
    }

    // Atualizar status do projeto para completado
    await db
      .update(projects)
      .set({ status: "completed", updatedAt: new Date() })
      .where(eq(projects.id, session.projectId));

    return NextResponse.json({ success: true, sessionId: session.id });
  } catch (error) {
    console.error("Erro ao finalizar sessão:", error);
    return NextResponse.json(
      { error: "Erro ao finalizar sessão" },
      { status: 500 }
    );
  }
}
