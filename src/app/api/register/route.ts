import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { users, verificationTokens } from "@/lib/db/schema";
import { eq } from "drizzle-orm";
import bcrypt from "bcryptjs";

export async function POST(req: Request) {
  try {
    const { name, email, password } = await req.json();

    if (!name || !email || !password) {
      return NextResponse.json(
        { message: "Todos os campos são obrigatórios." },
        { status: 400 }
      );
    }

    if (password.length < 8) {
      return NextResponse.json(
        { message: "A senha deve ter no mínimo 8 caracteres." },
        { status: 400 }
      );
    }

    // Verificar se o email já está em uso
    const existingUser = await db.select().from(users).where(eq(users.email, email)).limit(1);
    if (existingUser.length > 0) {
      return NextResponse.json(
        { message: "Este e-mail já está em uso." },
        { status: 400 }
      );
    }

    // Hash da senha
    const hashedPassword = await bcrypt.hash(password, 10);

    // Criar o usuário com email verificado e crédito inicial de 8 minutos (Plano Gratuito)
    const [newUser] = await db.insert(users).values({
      name,
      email,
      passwordHash: hashedPassword,
      emailVerified: new Date(),
      credits: 8, // 8 minutos de teste no plano gratuito
      subscriptionStatus: "free",
    }).returning({ id: users.id });

    return NextResponse.json(
      { message: "Conta criada com sucesso!" },
      { status: 201 }
    );
  } catch (error) {
    console.error("Erro ao registrar usuário:", error);
    return NextResponse.json(
      { message: "Ocorreu um erro interno ao criar sua conta. Tente novamente mais tarde." },
      { status: 500 }
    );
  }
}
