import { MetadataRoute } from 'next'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Hive Mind - Consultoria Multi-Agentes com IA',
    short_name: 'Hive Mind',
    description: 'Sessões de consultoria em tempo real com um painel de 5 especialistas de IA.',
    start_url: '/',
    display: 'standalone',
    background_color: '#030712', // bg-gray-950 equivalent
    theme_color: '#d4af37', // Gold color for branding
    icons: [
      {
        src: '/logo.png',
        sizes: '192x192',
        type: 'image/png',
        purpose: 'maskable'
      },
      {
        src: '/logo.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'maskable'
      }
    ],
  }
}
