import Stripe from "stripe";

export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY || "sk_test_dummy", {
  apiVersion: "2026-03-25.dahlia",
  typescript: true,
});

// IDs dos preços criados no Stripe
export const STRIPE_PRICES = {
  SESSION: "price_1TJOSZ3zDP3Guk8j5HK0IzSe",       // R$149,90 - Sessão Avulsa
  PROFESSIONAL: "price_1TJOSe3zDP3Guk8jnRJ0jZvN",  // R$399,90/mês - Profissional
} as const;

// Créditos por plano
export const PLAN_CREDITS: Record<string, number> = {
  [STRIPE_PRICES.SESSION]: 1,
  [STRIPE_PRICES.PROFESSIONAL]: 5,
};
