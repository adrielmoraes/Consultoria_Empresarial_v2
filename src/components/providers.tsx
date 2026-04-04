"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import { SessionProvider } from "next-auth/react";
import { ReactNode, useEffect } from "react";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <SessionProvider
      refetchInterval={0} // Desativa polling automático
      refetchOnWindowFocus={false} // Não refetch quando janela ganha foco
      refetchWhenOffline={false} // Não refetch quando offline
    >
      <NextThemesProvider attribute="class" defaultTheme="dark" enableSystem>
        <ClientPersistence>{children}</ClientPersistence>
      </NextThemesProvider>
    </SessionProvider>
  );
}

// Componente para manter estado do cliente entre reloads
function ClientPersistence({ children }: { children: ReactNode }) {
  useEffect(() => {
    // Marca que o cliente carregou completamente
    sessionStorage.setItem("client_ready", "true");
    
    // Registra Service Worker para PWA
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js').then(
          function(registration) {
            console.log('Service Worker registration successful with scope: ', registration.scope);
          },
          function(err) {
            console.log('Service Worker registration failed: ', err);
          }
        );
      });
    }

    // Previne reload em caso de visibilidade
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        // Marca que estava em background
        sessionStorage.setItem("was_background", "true");
      } else if (sessionStorage.getItem("was_background") === "true") {
        // Voltou do background - mas NÃO recarrega
        sessionStorage.removeItem("was_background");
        console.log("[ClientPersistence] Voltou do background, mantendo estado.");
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  return <>{children}</>;
}
