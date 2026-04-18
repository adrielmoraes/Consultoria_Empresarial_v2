import { NextRequest, NextResponse } from "next/server";
import { AccessToken, RoomServiceClient } from "livekit-server-sdk";

const MAX_GUESTS_PER_ROOM = 3;

async function getGuestParticipantCount(roomName: string): Promise<number | null> {
  const url = process.env.LIVEKIT_URL || process.env.NEXT_PUBLIC_LIVEKIT_URL;
  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;

  if (!url || !apiKey || !apiSecret) {
    return null;
  }

  const roomServiceClient = new RoomServiceClient(url, apiKey, apiSecret);

  try {
    const participants = await roomServiceClient.listParticipants(roomName);
    return participants.filter((participant) => {
      const identity = participant.identity ?? "";
      return identity.startsWith("guest-");
    }).length;
  } catch (error) {
    console.warn(
      `[Guest Token API] Falha ao listar convidados da sala ${roomName}:`,
      error
    );
    return null;
  }
}

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

    const currentGuestCount = await getGuestParticipantCount(roomName);

    if (currentGuestCount !== null && currentGuestCount >= MAX_GUESTS_PER_ROOM) {
      return NextResponse.json(
        {
          error: "Esta reuniao ja atingiu o limite de 3 convidados.",
          code: "GUEST_LIMIT_REACHED",
          maxGuests: MAX_GUESTS_PER_ROOM,
          currentGuestCount,
        },
        { status: 403 }
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
