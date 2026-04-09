import { NextRequest, NextResponse } from "next/server";
import { AccessToken } from "livekit-server-sdk";

/**
 * Gera um token de acesso LiveKit para convidados (guests) entrarem em uma sala.
 * Convidados possuem permissões restritas: podem publicar áudio e subscrever,
 * mas sua identidade começa com "guest-" para diferenciação no worker.
 */
export async function POST(request: NextRequest) {
  try {
    const { roomName, guestName } = await request.json();

    if (!roomName || !guestName) {
      return NextResponse.json(
        { error: "roomName e guestName são obrigatórios" },
        { status: 400 }
      );
    }

    const apiKey = process.env.LIVEKIT_API_KEY;
    const apiSecret = process.env.LIVEKIT_API_SECRET;

    if (!apiKey || !apiSecret) {
      return NextResponse.json(
        { error: "Configuração LiveKit ausente no servidor" },
        { status: 500 }
      );
    }

    // Gera identidade única com prefixo guest-
    const participantIdentity = `guest-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    const token = new AccessToken(apiKey, apiSecret, {
      identity: participantIdentity,
      name: guestName,
    });

    token.addGrant({
      room: roomName,
      roomJoin: true,
      canPublish: true,
      canSubscribe: true,
      canPublishData: true,
    });

    const url = process.env.LIVEKIT_URL || process.env.NEXT_PUBLIC_LIVEKIT_URL;
    const jwt = await token.toJwt();

    return NextResponse.json({ token: jwt, url, identity: participantIdentity });
  } catch (error) {
    console.error("Erro ao gerar token de guest LiveKit:", error);
    return NextResponse.json(
      { error: "Erro ao gerar token de acesso para convidado" },
      { status: 500 }
    );
  }
}
