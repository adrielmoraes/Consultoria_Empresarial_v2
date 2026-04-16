import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { mentoringSessions, executionPlans, projects } from "@/lib/db/schema";
import { eq } from "drizzle-orm";

export async function POST(request: NextRequest) {
  try {
    const payload = await request.json();
    const { sessionId, transcript } = payload;

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
    
    // Agora o frontend envia uma array de "documents"
    const docsToSave: Array<{ docType: string, title: string, content: string, pdfUrl: string | null }> =
      Array.isArray(payload.documents) ? payload.documents : [];

    // Fallback retrocompatibilidade (caso venha o formato antigo)
    const { markdownContent, pdfUrl } = payload;
    if (docsToSave.length === 0 && (markdownContent || pdfUrl)) {
      docsToSave.push({
        docType: "plano_execucao",
        title: "Plano de Execução",
        content: markdownContent || "",
        pdfUrl: pdfUrl || null
      });
    }

    // Inserir os documentos no banco iterativamente, sem sobrescrever
    for (const doc of docsToSave) {
      const finalMarkdown = doc.content.trim() || undefined; // Se não tiver não envia (na base vira NULL)
      const finalPdfUrl = typeof doc.pdfUrl === "string" && doc.pdfUrl.trim() ? doc.pdfUrl.trim() : null;

      if (finalMarkdown || finalPdfUrl) {
        await db.insert(executionPlans).values({
          sessionId,
          docType: doc.docType || "generico",
          title: doc.title || "Documento",
          pdfUrl: finalPdfUrl,
          markdownContent: finalMarkdown,
          generatedAt: new Date(),
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
