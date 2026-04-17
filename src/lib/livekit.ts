import { AccessToken } from "livekit-server-sdk";

/**
 * Gera um token de acesso LiveKit para um participante entrar em uma sala.
 * @param roomName - Nome da sala LiveKit.
 * @param participantName - Nome de exibição do participante.
 * @param participantIdentity - Identidade única do participante (ex: userId).
 * @param ttlSeconds - Time To Live do token em segundos. Se fornecido, o LiveKit
 *                     encerrará automaticamente a conexão quando o tempo expirar.
 *                     Use `creditos * 60` para converter minutos em segundos.
 */
export async function generateLiveKitToken(
  roomName: string,
  participantName: string,
  participantIdentity: string,
  ttlSeconds?: number
): Promise<string> {
  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;

  if (!apiKey || !apiSecret) {
    throw new Error("LIVEKIT_API_KEY e LIVEKIT_API_SECRET são obrigatórios");
  }

  const tokenOptions: ConstructorParameters<typeof AccessToken>[2] = {
    identity: participantIdentity,
    name: participantName,
  };

  // Se TTL for fornecido, define o tempo de vida do token em segundos.
  // Isso garante corte em nível de protocolo WebRTC — sem gambiarra de frontend.
  if (ttlSeconds && ttlSeconds > 0) {
    tokenOptions.ttl = `${ttlSeconds}s`;
  }

  const token = new AccessToken(apiKey, apiSecret, tokenOptions);

  token.addGrant({
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canSubscribe: true,
    canPublishData: true,
  });

  return await token.toJwt();
}
