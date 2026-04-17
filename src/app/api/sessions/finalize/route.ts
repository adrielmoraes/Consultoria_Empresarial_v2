import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { mentoringSessions, executionPlans, projects, users } from "@/lib/db/schema";
import { eq, sql } from "drizzle-orm";

export async function POST(request: NextRequest) {
  try {
    const payload = await request.json();
    const { sessionId, transcript } = payload;

    if (!sessionId) {
      return NextResponse.json({ error: "sessionId é obrigatório" }, { status: 400 });
    }

    const endedAt = new Date();

    // Atualizar sessão como concluída e capturar os dados de tempo
    const [session] = await db
      .update(mentoringSessions)
      .set({
        status: "completed",
        endedAt,
        transcript: transcript || null,
      })
      .where(eq(mentoringSessions.id, sessionId))
      .returning();

    if (!session) {
      return NextResponse.json({ error: "Sessão não encontrada" }, { status: 404 });
    }

    // --- DEDUÇÃO DE CRÉDITOS (MINUTOS) ---
    // Calcular a duração real da sessão em minutos (arredondado para cima)
    const duracaoMs = endedAt.getTime() - session.startedAt.getTime();
    const minutosGastos = Math.max(1, Math.ceil(duracaoMs / 60_000));

    console.log(
      `[Finalize API] Sessão ${sessionId} encerrada. ` +
      `Duração: ${minutosGastos} min (${Math.round(duracaoMs / 1000)}s). ` +
      `Debitando créditos do usuário...`
    );

    // Buscar o userId via projectId → projects
    const [project] = await db
      .select({ userId: projects.userId })
      .from(projects)
      .where(eq(projects.id, session.projectId))
      .limit(1);

    if (project?.userId) {
      // Usar expressão SQL para garantir que o saldo nunca fique negativo
      // GREATEST(credits - minutosGastos, 0) é a proteção atômica no banco
      await db
        .update(users)
        .set({
          credits: sql`GREATEST(${users.credits} - ${minutosGastos}, 0)`,
        })
        .where(eq(users.id, project.userId));

      console.log(
        `[Finalize API] ${minutosGastos} min debitados do usuário ${project.userId}.`
      );
    } else {
      console.warn(
        `[Finalize API] Não foi possível encontrar o userId para o projeto ${session.projectId}. Créditos não debitados.`
      );
    }

    const normalizedTranscript = typeof transcript === "string" ? transcript.trim() : "";

    // Agora o frontend envia uma array de "documents"
    const docsToSave: Array<{ docType: string; title: string; content: string; pdfUrl: string | null }> =
      Array.isArray(payload.documents) ? payload.documents : [];

    // Fallback retrocompatibilidade (caso venha o formato antigo)
    const { markdownContent, pdfUrl } = payload;
    if (docsToSave.length === 0 && (markdownContent || pdfUrl)) {
      docsToSave.push({
        docType: "plano_execucao",
        title: "Plano de Execução",
        content: markdownContent || "",
        pdfUrl: pdfUrl || null,
      });
    }

    // Inserir os documentos no banco iterativamente, sem sobrescrever
    for (const doc of docsToSave) {
      const finalMarkdown = doc.content.trim() || undefined;
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

    return NextResponse.json({
      success: true,
      sessionId: session.id,
      minutosDebitados: minutosGastos,
    });
  } catch (error) {
    console.error("Erro ao finalizar sessão:", error);
    return NextResponse.json(
      { error: "Erro ao finalizar sessão" },
      { status: 500 }
    );
  }
}
