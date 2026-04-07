import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { projects, mentoringSessions, executionPlans } from "@/lib/db/schema";
import { eq } from "drizzle-orm";

type PlanListItem = {
  id: string;
  projectTitle: string;
  projectId: string;
  sessionId: string;
  pdfUrl: string | null;
  hasMarkdown: boolean;
  generatedAt: string;
};

export async function GET(request: NextRequest) {
  try {
    const userId = request.nextUrl.searchParams.get("userId");

    if (!userId) {
      return NextResponse.json({ error: "userId é obrigatório" }, { status: 400 });
    }

    // Buscar projetos do usuário
    const userProjects = await db
      .select()
      .from(projects)
      .where(eq(projects.userId, userId));

    if (userProjects.length === 0) {
      return NextResponse.json({ plans: [] });
    }

    // Para cada projeto, buscar sessões e planos
    const allPlans: PlanListItem[] = [];

    for (const project of userProjects) {
      const sessions = await db
        .select()
        .from(mentoringSessions)
        .where(eq(mentoringSessions.projectId, project.id));

      for (const session of sessions) {
        const plans = await db
          .select()
          .from(executionPlans)
          .where(eq(executionPlans.sessionId, session.id));

        for (const plan of plans) {
          allPlans.push({
            id: plan.id,
            projectTitle: project.title,
            projectId: project.id,
            sessionId: session.id,
            pdfUrl: plan.pdfUrl,
            hasMarkdown: !!plan.markdownContent,
            generatedAt: plan.generatedAt.toISOString().split("T")[0],
          });
        }
      }
    }

    // Ordenar por data mais recente
    allPlans.sort((a, b) => new Date(b.generatedAt).getTime() - new Date(a.generatedAt).getTime());

    return NextResponse.json({ plans: allPlans });
  } catch (error) {
    console.error("Erro ao listar planos:", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }
}
