import Stripe from "stripe";

export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: "2026-02-25.clover" as any,
  typescript: true,
});

// IDs dos preços criados no Stripe
export const STRIPE_PRICES = {
  SESSION: "price_1TBokT3zDP3Guk8jHYOsGfB0",        // R$49 - Sessão Avulsa
  PROFESSIONAL: "price_1TBokT3zDP3Guk8j9TDmKT9s",    // R$149/mês - Profissional
  ENTERPRISE: "price_1TBokT3zDP3Guk8jTX0AzbOt",      // R$399/mês - Enterprise
} as const;

// Créditos por plano
export const PLAN_CREDITS: Record<string, number> = {
  [STRIPE_PRICES.SESSION]: 1,
  [STRIPE_PRICES.PROFESSIONAL]: 5,
  [STRIPE_PRICES.ENTERPRISE]: 999, // ilimitado
};
