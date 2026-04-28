import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { mentoringSessions, projects, users } from "@/lib/db/schema";
import { eq, and, desc } from "drizzle-orm";
import { AgentDispatchClient, RoomServiceClient } from "livekit-server-sdk";
import { auth } from "@/auth";

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

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const internalSecret = request.headers.get("x-internal-secret");
    const INTERNAL_API_SECRET = process.env.INTERNAL_API_SECRET || "";

    if (internalSecret !== INTERNAL_API_SECRET || !INTERNAL_API_SECRET) {
      console.warn("[Sessions API] Falha na autenticação interna via GET");
      return NextResponse.json({ error: "Não autorizado" }, { status: 401 });
    }

    const roomName = request.nextUrl.searchParams.get("roomName");
    if (!roomName) {
      return NextResponse.json({ error: "roomName é obrigatório" }, { status: 400 });
    }

    let [session] = await db
      .select({ id: mentoringSessions.id })
      .from(mentoringSessions)
      .where(eq(mentoringSessions.livekitRoomId, roomName))
      .limit(1);

    // Fallback: se não encontrou pela string exata do livekitRoomId,
    // tenta encontrar a sessão ativa mais recente para este projeto
    if (!session) {
      const projectMatch = roomName.match(/mentoria-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
      const projectId = projectMatch ? projectMatch[1] : null;
      
      if (projectId) {
        const fallbackSessions = await db
          .select({ id: mentoringSessions.id })
          .from(mentoringSessions)
          .where(and(
            eq(mentoringSessions.projectId, projectId),
            eq(mentoringSessions.status, "active")
          ))
          .orderBy(desc(mentoringSessions.startedAt)) // mais recente primeiro
          .limit(1);
          
        if (fallbackSessions.length > 0) {
          session = fallbackSessions[0];
          console.log(`[Sessions API] Fallback: Sessão encontrada pelo projectId ${projectId}`);
        }
      }
    }

    if (!session) {
      return NextResponse.json({ error: "Sessão não encontrada" }, { status: 404 });
    }

    return NextResponse.json({ sessionId: session.id });
  } catch (error) {
    console.error("[Sessions API] Erro ao buscar sessão por roomName:", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  try {
    // SEGURANÇA: userId extraído da sessão autenticada do servidor.
    // Impede que um hacker envie o userId de outra pessoa para gastar seus créditos.
    const authSession = await auth();

    if (!authSession?.user?.id) {
      return NextResponse.json(
        { error: "Não autenticado. Faça login para continuar." },
        { status: 401 }
      );
    }

    const userId = authSession.user.id;
    const { projectId } = await request.json();

    if (!projectId) {
      return NextResponse.json(
        { error: "projectId é obrigatório" },
        { status: 400 }
      );
    }

    // --- GUARDA DE SALDO: Bloquear despacho do agente se o usuário não tiver minutos ---
    const [userCredits] = await db
      .select({ credits: users.credits })
      .from(users)
      .where(eq(users.id, userId))
      .limit(1);

    if (!userCredits || (userCredits.credits ?? 0) < 1) {
      console.warn(`[Sessions API] Usuário ${userId} bloqueado — saldo insuficiente (${userCredits?.credits ?? 0} min).`);
      return NextResponse.json(
        { error: "Sem minutos disponíveis. Assine um plano para continuar.", code: "NO_CREDITS" },
        { status: 403 }
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

    const roomPrefix = `mentoria-${projectId}`;

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
      const existingRoomName = existingSession.livekitRoomId ?? roomPrefix;
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

    // Garantir que a nova sala seja sempre única para contornar lentidão na limpeza do Worker
    const uniqueRoomName = `${roomPrefix}-${crypto.randomUUID().split("-")[0]}`;

    // Criar nova sessão
    const [session] = await db
      .insert(mentoringSessions)
      .values({
        projectId,
        livekitRoomId: uniqueRoomName,
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
      await dispatchAgent(uniqueRoomName);
    } catch (dispatchError) {
      console.error("[Sessions API] Erro ao disparar agente:", dispatchError);
    }

    return NextResponse.json({ sessionId: session.id, roomName: uniqueRoomName });
  } catch (error) {
    console.error("Erro ao criar sessão:", error);
    return NextResponse.json(
      { error: "Erro ao criar sessão de mentoria" },
      { status: 500 }
    );
  }
}
