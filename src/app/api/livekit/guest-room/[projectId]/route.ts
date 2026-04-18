import { NextRequest, NextResponse } from "next/server";
import { and, desc, eq } from "drizzle-orm";
import { db } from "@/lib/db";
import { mentoringSessions } from "@/lib/db/schema";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> },
) {
  const { projectId } = await params;

  try {
    if (!projectId) {
      return NextResponse.json(
        { error: "ProjectId do convite nao informado." },
        { status: 400 },
      );
    }

    const [activeSession] = await db
      .select({
        sessionId: mentoringSessions.id,
        roomName: mentoringSessions.livekitRoomId,
      })
      .from(mentoringSessions)
      .where(
        and(
          eq(mentoringSessions.projectId, projectId),
          eq(mentoringSessions.status, "active"),
        ),
      )
      .orderBy(desc(mentoringSessions.startedAt))
      .limit(1);

    if (!activeSession?.roomName) {
      return NextResponse.json(
        { error: "Nenhuma reuniao ativa foi encontrada para este convite." },
        { status: 404 },
      );
    }

    return NextResponse.json({
      sessionId: activeSession.sessionId,
      roomName: activeSession.roomName,
    });
  } catch (error) {
    console.error("Erro ao resolver sala ativa do convite:", error);
    return NextResponse.json(
      { error: "Erro interno ao validar convite." },
      { status: 500 },
    );
  }
}
