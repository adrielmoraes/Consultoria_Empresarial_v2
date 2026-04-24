import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { executionPlans, mentoringSessions } from "@/lib/db/schema";
import { eq } from "drizzle-orm";

const INTERNAL_API_SECRET = process.env.INTERNAL_API_SECRET || "";

export async function POST(request: NextRequest) {
  try {
    const internalSecret = request.headers.get("x-internal-secret");

    // Endpoint seguro para uso apenas via Worker Python ou backend-to-backend
    if (internalSecret !== INTERNAL_API_SECRET) {
      return NextResponse.json(
        { error: "Não autorizado." },
        { status: 401 }
      );
    }

    const { sessionId, docType, title, markdownContent, pdfBase64 } = await request.json();

    if (!sessionId || !markdownContent) {
      return NextResponse.json({ error: "sessionId e markdownContent são obrigatórios" }, { status: 400 });
    }

    // Verificar se a sessão existe
    const session = await db.query.mentoringSessions.findFirst({
      where: eq(mentoringSessions.id, sessionId),
    });

    if (!session) {
      return NextResponse.json({ error: "Sessão não encontrada" }, { status: 404 });
    }

    // Inserir o documento (Plano de Execução, Guia, etc.)
    const [plan] = await db.insert(executionPlans).values({
      sessionId,
      docType: docType || "plano_execucao",
      title: title || "Plano de Execução",
      markdownContent,
      pdfUrl: pdfBase64 || null, // Armazena o Base64 DataURI gerado pelo Python
    }).returning();

    return NextResponse.json({ success: true, plan });
  } catch (error) {
    console.error("Erro ao salvar documento (execution_plan):", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }
}
