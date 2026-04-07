import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { executionPlans, mentoringSessions } from "@/lib/db/schema";
import { eq } from "drizzle-orm";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  try {
    const { sessionId } = await params;
    const format = request.nextUrl.searchParams.get("format");

    if (!sessionId) {
      return NextResponse.json({ error: "sessionId é obrigatório" }, { status: 400 });
    }

    const session = await db.query.mentoringSessions.findFirst({
      where: eq(mentoringSessions.id, sessionId),
      with: {
        project: {
          with: {
            user: true,
          },
        },
      },
    });

    if (!session) {
      return NextResponse.json({ error: "Sessão não encontrada" }, { status: 404 });
    }

    const plan = await db.query.executionPlans.findFirst({
      where: eq(executionPlans.sessionId, sessionId),
      orderBy: (plans, { desc }) => [desc(plans.generatedAt)],
    });

    if (!plan) {
      return NextResponse.json({ error: "Plano não encontrado" }, { status: 404 });
    }

    if (format !== "json") {
      if (plan.pdfUrl) {
        return NextResponse.redirect(plan.pdfUrl);
      }

      if (plan.markdownContent) {
        return new NextResponse(plan.markdownContent, {
          headers: {
            "Content-Type": "text/markdown; charset=utf-8",
            "Content-Disposition": `inline; filename="plano-${sessionId}.md"`,
          },
        });
      }
    }

    return NextResponse.json({
      plan: {
        id: plan.id,
        pdfUrl: plan.pdfUrl,
        markdownContent: plan.markdownContent,
        generatedAt: plan.generatedAt,
      },
      session: {
        id: session.id,
        startedAt: session.startedAt,
        endedAt: session.endedAt,
      },
      project: {
        id: session.project.id,
        title: session.project.title,
      },
      user: {
        name: session.project.user?.name || "Usuário",
      },
    });
  } catch (error) {
    console.error("Erro ao buscar plano:", error);
    return NextResponse.json({ error: "Erro ao buscar plano" }, { status: 500 });
  }
}
