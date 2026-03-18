import { AccessToken } from "livekit-server-sdk";

/**
 * Gera um token de acesso LiveKit para um participante entrar em uma sala.
 */
export async function generateLiveKitToken(
  roomName: string,
  participantName: string,
  participantIdentity: string
): Promise<string> {
  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;

  if (!apiKey || !apiSecret) {
    throw new Error("LIVEKIT_API_KEY e LIVEKIT_API_SECRET são obrigatórios");
  }

  const token = new AccessToken(apiKey, apiSecret, {
    identity: participantIdentity,
    name: participantName,
  });

  token.addGrant({
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canSubscribe: true,
    canPublishData: true,
  });

  return await token.toJwt();
}
