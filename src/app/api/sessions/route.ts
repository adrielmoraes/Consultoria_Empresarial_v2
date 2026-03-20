import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { mentoringSessions, projects } from "@/lib/db/schema";
import { eq, and } from "drizzle-orm";
import { AgentDispatchClient } from "livekit-server-sdk";

export async function POST(request: NextRequest) {
  try {
    const { projectId, userId } = await request.json();

    if (!projectId || !userId) {
      return NextResponse.json(
        { error: "projectId e userId são obrigatórios" },
        { status: 400 }
      );
    }

    // Verificar se o projeto pertence ao usuário
    const [project] = await db
      .select()
      .from(projects)
      .where(eq(projects.id, projectId))
      .limit(1);

    if (!project || project.userId !== userId) {
      return NextResponse.json({ error: "Projeto não encontrado" }, { status: 404 });
    }

    // Criar nome da sala com o ID do projeto
    const roomName = `mentoria-${projectId}`;

    // Idempotência: se já existe sessão ativa para este projeto, reutiliza sem criar nova dispatch
    const [existingSession] = await db
      .select()
      .from(mentoringSessions)
      .where(and(
        eq(mentoringSessions.projectId, projectId),
        eq(mentoringSessions.status, "active")
      ))
      .limit(1);

    if (existingSession) {
      console.log(`[Sessions API] Sessão ativa já existe para ${roomName} — reutilizando.`);
      return NextResponse.json({
        sessionId: existingSession.id,
        roomName: existingSession.livekitRoomId ?? roomName,
      });
    }

    // Criar sessão de mentoria no banco
    const [session] = await db
      .insert(mentoringSessions)
      .values({
        projectId,
        livekitRoomId: roomName,
        status: "active",
      })
      .returning();

    // Atualizar o status do projeto para "in_progress"
    await db
      .update(projects)
      .set({ status: "in_progress", updatedAt: new Date() })
      .where(eq(projects.id, projectId));

    // Iniciar o Agente de Mentoria via Dispatch API
    try {
      const dispatchClient = new AgentDispatchClient(
        process.env.LIVEKIT_URL!,
        process.env.LIVEKIT_API_KEY!,
        process.env.LIVEKIT_API_SECRET!
      );
      await dispatchClient.createDispatch(roomName, "mentoria-agent");
      console.log(`[Sessions API] Agent dispatch criado para a sala ${roomName}`);
    } catch (dispatchError) {
      console.error("[Sessions API] Erro ao disparar agente:", dispatchError);
      // Não falha a resposta, mas loga o erro de dispatch
    }

    return NextResponse.json({
      sessionId: session.id,
      roomName,
    });
  } catch (error) {
    console.error("Erro ao criar sessão:", error);
    return NextResponse.json(
      { error: "Erro ao criar sessão de mentoria" },
      { status: 500 }
    );
  }
}
