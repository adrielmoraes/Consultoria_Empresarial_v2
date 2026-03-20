import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { users, projects, mentoringSessions, executionPlans } from "@/lib/db/schema";
import { eq, inArray, desc } from "drizzle-orm";

export async function GET(request: NextRequest) {
  try {
    const userId = request.nextUrl.searchParams.get("userId");

    if (!userId) {
      return NextResponse.json({ error: "userId é obrigatório" }, { status: 400 });
    }

    // Query 1: usuário
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

    // Query 2: todos os projetos do usuário
    const userProjects = await db
      .select()
      .from(projects)
      .where(eq(projects.userId, userId))
      .orderBy(desc(projects.createdAt));

    if (userProjects.length === 0) {
      return NextResponse.json({
        user,
        projects: [],
        stats: { totalProjects: 0, totalSessions: 0, totalPlans: 0, totalTime: "0m", credits: user.credits || 0 },
      });
    }

    const projectIds = userProjects.map((p) => p.id);

    // Query 3: todas as sessões dos projetos de uma vez
    const allSessions = await db
      .select()
      .from(mentoringSessions)
      .where(inArray(mentoringSessions.projectId, projectIds));

    // Query 4: todos os planos das sessões de uma vez
    const sessionIds = allSessions.map((s) => s.id);
    const allPlans = sessionIds.length > 0
      ? await db.select().from(executionPlans).where(inArray(executionPlans.sessionId, sessionIds))
      : [];

    // Indexar em memória
    const plansBySession = new Map<string, typeof allPlans>();
    for (const plan of allPlans) {
      const list = plansBySession.get(plan.sessionId) ?? [];
      list.push(plan);
      plansBySession.set(plan.sessionId, list);
    }

    const sessionsByProject = new Map<string, typeof allSessions>();
    for (const session of allSessions) {
      const list = sessionsByProject.get(session.projectId) ?? [];
      list.push(session);
      sessionsByProject.set(session.projectId, list);
    }

    // Calcular estatísticas
    let totalSessions = 0;
    let totalTimeSeconds = 0;
    let totalPlans = 0;

    for (const session of allSessions) {
      totalSessions++;
      if (session.endedAt && session.startedAt) {
        totalTimeSeconds += Math.floor(
          (session.endedAt.getTime() - session.startedAt.getTime()) / 1000
        );
      }
      totalPlans += (plansBySession.get(session.id) ?? []).length;
    }

    const totalHours = Math.floor(totalTimeSeconds / 3600);
    const totalMinutes = Math.floor((totalTimeSeconds % 3600) / 60);
    const totalTimeFormatted = totalHours > 0 ? `${totalHours}h ${totalMinutes}m` : `${totalMinutes}m`;

    // Montar projetos com flag de PDF
    const projectsWithPdf = userProjects.map((project) => {
      const sessions = sessionsByProject.get(project.id) ?? [];
      const hasPdf = sessions.some((s) => (plansBySession.get(s.id) ?? []).length > 0);
      return {
        id: project.id,
        title: project.title,
        description: project.description,
        status: project.status as "pending" | "in_progress" | "completed",
        createdAt: project.createdAt.toISOString().split("T")[0],
        hasPdf,
      };
    });

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
