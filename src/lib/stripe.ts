import Stripe from "stripe";

export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY || "sk_test_dummy", {
  apiVersion: "2026-02-25.clover",
  typescript: true,
});

// IDs dos produtos e preços criados no painel da Stripe (LIVE MODE)
// Produtos: prod_UM1wCHqJbi98bJ (Executivo) | prod_UM1zG3sYLCC9Mq (Profissional)
export const STRIPE_PRICES = {
  SESSION:      "price_1TNJuY3zDP3Guk8jomPvg9Ni", // R$497,90/mês  — Plano Executivo  (80 min)
  PROFESSIONAL: "price_1TNJwv3zDP3Guk8jAI7Ap7jo",  // R$1.197,90/mês — Plano Profissional (200 min)
} as const;

/**
 * Minutos totais liberados por plano após checkout bem-sucedido.
 * O webhook do Stripe usa este mapa para creditar o usuário no banco.
 *
 * Plano Executivo    → 80  minutos (R$497,90/mês)
 * Plano Profissional → 200 minutos (R$1.197,90/mês)
 */
export const PLAN_CREDITS: Record<string, number> = {
  [STRIPE_PRICES.SESSION]:      80,  // Plano Executivo: 80 minutos
  [STRIPE_PRICES.PROFESSIONAL]: 200, // Plano Profissional: 200 minutos
};
