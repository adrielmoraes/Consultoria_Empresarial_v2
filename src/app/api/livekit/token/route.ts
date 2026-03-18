import { NextRequest, NextResponse } from "next/server";
import { generateLiveKitToken } from "@/lib/livekit";

export async function POST(request: NextRequest) {
  try {
    const { roomName, participantName, participantIdentity } = await request.json();

    if (!roomName || !participantName || !participantIdentity) {
      return NextResponse.json(
        { error: "roomName, participantName e participantIdentity são obrigatórios" },
        { status: 400 }
      );
    }

    const token = await generateLiveKitToken(roomName, participantName, participantIdentity);

    const url = process.env.LIVEKIT_URL || process.env.NEXT_PUBLIC_LIVEKIT_URL;
    return NextResponse.json({ token, url });
  } catch (error) {
    console.error("Erro ao gerar token LiveKit:", error);
    return NextResponse.json(
      { error: "Erro ao gerar token de acesso" },
      { status: 500 }
    );
  }
}
