import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { mentoringSessions, projects } from "@/lib/db/schema";
import { eq } from "drizzle-orm";
import { v4 as uuidv4 } from "uuid";

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
