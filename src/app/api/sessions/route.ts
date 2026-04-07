import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { mentoringSessions, projects } from "@/lib/db/schema";
import { eq, and } from "drizzle-orm";
import { AgentDispatchClient, RoomServiceClient } from "livekit-server-sdk";

const DISPATCH_DEDUP_WINDOW_MS = 30_000; // 30 segundos

async function dispatchAgent(roomName: string) {
  const dispatchClient = new AgentDispatchClient(
    process.env.LIVEKIT_URL!,
    process.env.LIVEKIT_API_KEY!,
    process.env.LIVEKIT_API_SECRET!
  );
  await dispatchClient.createDispatch(roomName, "mentoria-agent");
  console.log(`[Sessions API] Agent dispatch criado para a sala ${roomName}`);
}

async function getNonAgentParticipantCount(roomName: string): Promise<number | null> {
  const roomServiceClient = new RoomServiceClient(
    process.env.LIVEKIT_URL!,
    process.env.LIVEKIT_API_KEY!,
    process.env.LIVEKIT_API_SECRET!,
  );

  try {
    const participants = await roomServiceClient.listParticipants(roomName);
    return participants.filter((participant) => {
      const identity = participant.identity ?? "";
      return !identity.startsWith("agent-");
    }).length;
  } catch (error) {
    console.warn(`[Sessions API] Falha ao listar participantes da sala ${roomName}:`, error);
    return null;
  }
}

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

    const roomName = `mentoria-${projectId}`;

    // Busca sessão ativa existente
    const [existingSession] = await db
      .select()
      .from(mentoringSessions)
      .where(and(
        eq(mentoringSessions.projectId, projectId),
        eq(mentoringSessions.status, "active")
      ))
      .limit(1);

    if (existingSession) {
      const existingRoomName = existingSession.livekitRoomId ?? roomName;
      const ageMs = Date.now() - existingSession.startedAt.getTime();
      const nonAgentParticipantCount = await getNonAgentParticipantCount(existingRoomName);

      if (nonAgentParticipantCount !== null && nonAgentParticipantCount > 0) {
        console.log(
          `[Sessions API] Sessão ativa reutilizada (${Math.round(ageMs / 1000)}s) com ${nonAgentParticipantCount} participante(s) não-agent em ${existingRoomName}.`,
        );
        return NextResponse.json({
          sessionId: existingSession.id,
          roomName: existingRoomName,
        });
      }

      if (nonAgentParticipantCount === null && ageMs <= DISPATCH_DEDUP_WINDOW_MS) {
        try {
          await dispatchAgent(existingRoomName);
        } catch (dispatchError) {
          console.error("[Sessions API] Erro ao redisparar agente em sessão reutilizada:", dispatchError);
        }
        console.log(
          `[Sessions API] Sessão recente reutilizada (${Math.round(ageMs / 1000)}s) sem confirmação de participantes em ${existingRoomName}.`,
        );
        return NextResponse.json({
          sessionId: existingSession.id,
          roomName: existingRoomName,
        });
      }

      console.log(
        `[Sessions API] Encerrando sessão ativa anterior (${Math.round(ageMs / 1000)}s) para recriar ${existingRoomName}.`,
      );
      await db
        .update(mentoringSessions)
        .set({ status: "cancelled", endedAt: new Date() })
        .where(eq(mentoringSessions.id, existingSession.id));
    }

    // Criar nova sessão
    const [session] = await db
      .insert(mentoringSessions)
      .values({
        projectId,
        livekitRoomId: roomName,
        status: "active",
      })
      .returning();

    // Atualizar status do projeto
    await db
      .update(projects)
      .set({ status: "in_progress", updatedAt: new Date() })
      .where(eq(projects.id, projectId));

    // Despachar agente
    try {
      await dispatchAgent(roomName);
    } catch (dispatchError) {
      console.error("[Sessions API] Erro ao disparar agente:", dispatchError);
    }

    return NextResponse.json({ sessionId: session.id, roomName });
  } catch (error) {
    console.error("Erro ao criar sessão:", error);
    return NextResponse.json(
      { error: "Erro ao criar sessão de mentoria" },
      { status: 500 }
    );
  }
}
