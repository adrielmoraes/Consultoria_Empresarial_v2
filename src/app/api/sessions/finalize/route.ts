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

    const normalizedTranscript = typeof transcript === "string" ? transcript.trim() : "";
    const normalizedMarkdown = typeof markdownContent === "string" ? markdownContent.trim() : "";
    const fallbackMarkdown =
      normalizedTranscript.length > 0
        ? `# Plano de Execução\n\n## Resumo da Sessão\n\nEste plano foi salvo automaticamente a partir da sessão finalizada.\n\n## Transcrição\n\n${normalizedTranscript}`
        : "";
    const finalMarkdown = normalizedMarkdown || fallbackMarkdown || null;
    const finalPdfUrl = typeof pdfUrl === "string" && pdfUrl.trim() ? pdfUrl.trim() : null;

    if (finalMarkdown || finalPdfUrl) {
      const existingPlan = await db.query.executionPlans.findFirst({
        where: eq(executionPlans.sessionId, sessionId),
      });

      if (existingPlan) {
        await db
          .update(executionPlans)
          .set({
            pdfUrl: finalPdfUrl,
            markdownContent: finalMarkdown,
            generatedAt: new Date(),
          })
          .where(eq(executionPlans.id, existingPlan.id));
      } else {
        await db.insert(executionPlans).values({
          sessionId,
          pdfUrl: finalPdfUrl,
          markdownContent: finalMarkdown,
        });
      }
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
