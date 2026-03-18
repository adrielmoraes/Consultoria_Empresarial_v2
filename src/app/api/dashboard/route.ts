import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { users, projects, mentoringSessions, executionPlans } from "@/lib/db/schema";
import { eq, count, sum, desc } from "drizzle-orm";

export async function GET(request: NextRequest) {
  try {
    const userId = request.nextUrl.searchParams.get("userId");

    if (!userId) {
      return NextResponse.json({ error: "userId é obrigatório" }, { status: 400 });
    }

    // Dados do usuário
    const [user] = await db
      .select({
        id: users.id,
        name: users.name,
        email: users.email,
        credits: users.credits,
        subscriptionStatus: users.subscriptionStatus,
        createdAt: users.createdAt,
      })
      .from(users)
      .where(eq(users.id, userId));

    if (!user) {
      return NextResponse.json({ error: "Usuário não encontrado" }, { status: 404 });
    }

    // Projetos do usuário com status
    const userProjects = await db
      .select()
      .from(projects)
      .where(eq(projects.userId, userId))
      .orderBy(desc(projects.createdAt));

    // Contagem de mentorias (sessões) do usuário
    const projectIds = userProjects.map((p) => p.id);

    let totalSessions = 0;
    let totalTimeSeconds = 0;
    let totalPlans = 0;

    if (projectIds.length > 0) {
      // Para cada projeto, buscar sessões
      for (const projectId of projectIds) {
        const sessions = await db
          .select()
          .from(mentoringSessions)
          .where(eq(mentoringSessions.projectId, projectId));

        totalSessions += sessions.length;

        // Calcular tempo total das sessões finalizadas
        for (const session of sessions) {
          if (session.endedAt && session.startedAt) {
            totalTimeSeconds += Math.floor(
              (session.endedAt.getTime() - session.startedAt.getTime()) / 1000
            );
          }
        }

        // Contar planos de execução
        for (const session of sessions) {
          const plans = await db
            .select()
            .from(executionPlans)
            .where(eq(executionPlans.sessionId, session.id));
          totalPlans += plans.length;
        }
      }
    }

    // Formatar tempo total
    const totalHours = Math.floor(totalTimeSeconds / 3600);
    const totalMinutes = Math.floor((totalTimeSeconds % 3600) / 60);
    const totalTimeFormatted =
      totalHours > 0 ? `${totalHours}h ${totalMinutes}m` : `${totalMinutes}m`;

    // Montar projetos com flag de PDF
    const projectsWithPdf = await Promise.all(
      userProjects.map(async (project) => {
        // Verificar se alguma sessão tem plano de execução
        const sessions = await db
          .select()
          .from(mentoringSessions)
          .where(eq(mentoringSessions.projectId, project.id));

        let hasPdf = false;
        for (const session of sessions) {
          const plans = await db
            .select()
            .from(executionPlans)
            .where(eq(executionPlans.sessionId, session.id));
          if (plans.length > 0) {
            hasPdf = true;
            break;
          }
        }

        return {
          id: project.id,
          title: project.title,
          description: project.description,
          status: project.status as "pending" | "in_progress" | "completed",
          createdAt: project.createdAt.toISOString().split("T")[0],
          hasPdf,
        };
      })
    );

    return NextResponse.json({
      user,
      projects: projectsWithPdf,
      stats: {
        totalProjects: userProjects.length,
        totalSessions,
        totalPlans,
        totalTime: totalTimeFormatted,
        credits: user.credits || 0,
      },
    });
  } catch (error) {
    console.error("Erro ao carregar dashboard:", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }
}
