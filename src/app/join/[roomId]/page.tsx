"use client";

import { useEffect } from "react";
import { useRouter, useParams } from "next/navigation";
import { Loader2 } from "lucide-react";

export default function JoinRoomRedirect() {
  const router = useRouter();
  const { roomId } = useParams();

  useEffect(() => {
    if (roomId) {
      // Redireciona para a rota correta de mentoria
      router.push(`/mentorship/${roomId}`);
    }
  }, [roomId, router]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#030712] text-white">
      <div className="w-16 h-16 rounded-2xl bg-[#0a0a0f] border border-[#d4af37]/30 flex items-center justify-center p-2 mb-6">
        <img src="/logo-icon.svg?v=2" alt="Hive Mind" className="w-full h-full object-contain animate-pulse" style={{ filter: 'brightness(0) saturate(100%) invert(76%) sepia(63%) saturate(456%) hue-rotate(8deg) brightness(96%) contrast(90%)' }} />
      </div>
      <div className="flex items-center gap-3 text-gray-400 font-medium">
        <Loader2 className="w-5 h-5 animate-spin text-[#d4af37]" />
        Conectando à sala de comando...
      </div>
    </div>
  );
}
