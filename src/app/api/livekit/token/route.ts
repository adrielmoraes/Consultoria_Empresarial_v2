import { NextRequest, NextResponse } from "next/server";
import { generateLiveKitToken } from "@/lib/livekit";
import { db } from "@/lib/db";
import { users } from "@/lib/db/schema";
import { eq } from "drizzle-orm";
import { auth } from "@/auth";

export async function POST(request: NextRequest) {
  try {
    // SEGURANÇA: Validar sessão autenticada antes de gerar token.
    const session = await auth();

    if (!session?.user?.id) {
      return NextResponse.json(
        { error: "Não autenticado. Faça login para continuar." },
        { status: 401 }
      );
    }

    const { roomName, participantName, participantIdentity } = await request.json();

    if (!roomName || !participantName || !participantIdentity) {
      return NextResponse.json(
        { error: "roomName, participantName e participantIdentity são obrigatórios" },
        { status: 400 }
      );
    }

    // SEGURANÇA: Garantir que o participantIdentity contém o ID do usuário autenticado.
    // Impede que alguém forje uma identity com o userId de outro para roubar créditos.
    const userIdMatch = participantIdentity.match(/^user-(.+)-\d+$/);
    const rawUserId = userIdMatch ? userIdMatch[1] : participantIdentity;

    if (rawUserId !== session.user.id) {
      console.warn(`[Token API] IDOR bloqueado: sessão=${session.user.id}, identity=${rawUserId}`);
      return NextResponse.json(
        { error: "Identidade do participante não corresponde ao usuário autenticado." },
        { status: 403 }
      );
    }

    // --- GUARDA DE SALDO: Verificar créditos (minutos) do usuário ---
    // rawUserId já extraído e validado contra a sessão acima.

    const [user] = await db
      .select({ credits: users.credits })
      .from(users)
      .where(eq(users.id, rawUserId))
      .limit(1);

    if (!user) {
      return NextResponse.json(
        { error: "Usuário não encontrado" },
        { status: 404 }
      );
    }

    const creditosRestantes = user.credits ?? 0;

    // Bloquear acesso categoricamente se o usuário não tiver ao menos 1 minuto
    if (creditosRestantes < 1) {
      console.warn(`[Token API] Usuário ${participantIdentity} bloqueado — saldo zerado (${creditosRestantes} min).`);
      return NextResponse.json(
        { error: "Sem minutos disponíveis. Assine um plano para continuar.", code: "NO_CREDITS" },
        { status: 403 }
      );
    }

    // Converter minutos restantes em segundos para usar como TTL do token.
    // O LiveKit cortará a conexão automaticamente quando o tempo acabar.
    const ttlSeconds = creditosRestantes * 60;

    console.log(`[Token API] Gerando token para ${participantIdentity} com TTL de ${creditosRestantes} min (${ttlSeconds}s).`);

    const token = await generateLiveKitToken(
      roomName,
      participantName,
      participantIdentity,
      ttlSeconds
    );

    const url = process.env.LIVEKIT_URL || process.env.NEXT_PUBLIC_LIVEKIT_URL;
    return NextResponse.json({ token, url, maxDurationSeconds: ttlSeconds });
  } catch (error) {
    console.error("Erro ao gerar token LiveKit:", error);
    return NextResponse.json(
      { error: "Erro ao gerar token de acesso" },
      { status: 500 }
    );
  }
}
