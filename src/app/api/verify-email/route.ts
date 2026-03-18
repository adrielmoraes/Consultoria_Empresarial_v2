import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { users, verificationTokens } from "@/lib/db/schema";
import { eq } from "drizzle-orm";

export async function GET(req: Request) {
  try {
    const { searchParams } = new URL(req.url);
    const token = searchParams.get("token");

    if (!token) {
      return NextResponse.json({ message: "Token inválido ou não fornecido." }, { status: 400 });
    }

    // Buscar o token no banco
    const dbToken = await db
      .select()
      .from(verificationTokens)
      .where(eq(verificationTokens.token, token))
      .limit(1);

    if (dbToken.length === 0) {
      return NextResponse.json({ message: "Token inválido ou expirado." }, { status: 400 });
    }

    const verificationRecord = dbToken[0];

    // Verificar se expirou
    if (new Date() > new Date(verificationRecord.expires)) {
      return NextResponse.json({ message: "O link de verificação expirou." }, { status: 400 });
    }

    // Confirmar e-mail do usuário
    await db
      .update(users)
      .set({ emailVerified: new Date() })
      .where(eq(users.email, verificationRecord.identifier));

    // Remover o token
    await db
      .delete(verificationTokens)
      .where(eq(verificationTokens.token, token));

    return NextResponse.redirect(new URL("/login?verified=true", req.url));
  } catch (error) {
    console.error("Erro na verificação de e-mail:", error);
    return NextResponse.json({ message: "Ocorreu um erro ao verificar o e-mail." }, { status: 500 });
  }
}
