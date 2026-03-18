import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { projects, users } from "@/lib/db/schema";
import { eq } from "drizzle-orm";

// Criar novo projeto
export async function POST(request: NextRequest) {
  try {
    const { userId, title, description } = await request.json();

    if (!userId || !title) {
      return NextResponse.json({ error: "Dados incompletos" }, { status: 400 });
    }

    // Verificar créditos do usuário
    const [user] = await db.select().from(users).where(eq(users.id, userId));

    if (!user) {
      return NextResponse.json({ error: "Usuário não encontrado" }, { status: 404 });
    }

    if ((user.credits || 0) <= 0 && user.subscriptionStatus !== "active") {
      return NextResponse.json(
        { error: "Sem créditos disponíveis. Adquira um plano para continuar." },
        { status: 403 }
      );
    }

    // Criar o projeto
    const [project] = await db
      .insert(projects)
      .values({
        userId,
        title,
        description,
        status: "pending",
      })
      .returning();

    // Descontar crédito
    await db
      .update(users)
      .set({
        credits: Math.max(0, (user.credits || 0) - 1),
        updatedAt: new Date(),
      })
      .where(eq(users.id, userId));

    return NextResponse.json({ project });
  } catch (error) {
    console.error("Erro ao criar projeto:", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }
}

// Listar projetos do usuário
export async function GET(request: NextRequest) {
  try {
    const userId = request.nextUrl.searchParams.get("userId");

    if (!userId) {
      return NextResponse.json({ error: "userId é obrigatório" }, { status: 400 });
    }

    const userProjects = await db
      .select()
      .from(projects)
      .where(eq(projects.userId, userId))
      .orderBy(projects.createdAt);

    return NextResponse.json({ projects: userProjects });
  } catch (error) {
    console.error("Erro ao listar projetos:", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }
}
