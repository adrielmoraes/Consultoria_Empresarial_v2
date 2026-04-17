import { NextRequest, NextResponse } from "next/server";
import { stripe, PLAN_CREDITS } from "@/lib/stripe";
import { db } from "@/lib/db";
import { users } from "@/lib/db/schema";
import { eq, sql } from "drizzle-orm";
import Stripe from "stripe";

export async function POST(request: NextRequest) {
  const body = await request.text();
  const signature = request.headers.get("stripe-signature") as string;

  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(
      body,
      signature,
      process.env.STRIPE_WEBHOOK_SECRET!
    );
  } catch (err) {
    console.error("⚠️ Webhook signature verification falhou:", err);
    return NextResponse.json({ error: "Webhook inválido" }, { status: 400 });
  }

  try {
    switch (event.type) {
      // Pagamento avulso completo
      case "checkout.session.completed": {
        const session = event.data.object as Stripe.Checkout.Session;
        const userId = session.metadata?.userId;
        const priceId = session.metadata?.priceId;

        if (!userId || !priceId) break;

        const creditsToAdd = PLAN_CREDITS[priceId] || 0;

        if (session.mode === "payment") {
          // Pagamento avulso — soma atômica via SQL (evita race condition)
          await db
            .update(users)
            .set({
              credits: sql`COALESCE(${users.credits}, 0) + ${creditsToAdd}`,
              stripeCustomerId: session.customer as string,
              updatedAt: new Date(),
            })
            .where(eq(users.id, userId));
          console.log(`[Webhook] Pagamento avulso: +${creditsToAdd} min para o usuário ${userId}.`);
        } else if (session.mode === "subscription") {
          // Nova assinatura — reset para os minutos do plano
          await db
            .update(users)
            .set({
              subscriptionStatus: "active",
              credits: creditsToAdd,
              stripeCustomerId: session.customer as string,
              updatedAt: new Date(),
            })
            .where(eq(users.id, userId));
          console.log(`[Webhook] Nova assinatura: ${creditsToAdd} min para o usuário ${userId}.`);
        }
        break;
      }

      // Assinatura renovada
      case "invoice.paid": {
        const invoice = event.data.object as Stripe.Invoice;
        const customerId = invoice.customer as string;

        if (invoice.billing_reason === "subscription_cycle") {
          const lineItem = invoice.lines.data[0] as Stripe.InvoiceLineItem | undefined;
          const priceData = lineItem?.pricing?.price_details?.price;
          const priceId = typeof priceData === "string" ? priceData : priceData?.id;
          const creditsToAdd = priceId ? PLAN_CREDITS[priceId] || 0 : 0;

          await db
            .update(users)
            .set({
              credits: creditsToAdd,
              subscriptionStatus: "active",
              updatedAt: new Date(),
            })
            .where(eq(users.stripeCustomerId, customerId));
          console.log(`[Webhook] Renovação mensal: ${creditsToAdd} min para o cliente ${customerId}.`);
        }
        break;
      }

      // Assinatura cancelada
      case "customer.subscription.deleted": {
        const subscription = event.data.object as Stripe.Subscription;
        const customerId = subscription.customer as string;

        await db
          .update(users)
          .set({
            subscriptionStatus: "cancelled",
            credits: 0,
            updatedAt: new Date(),
          })
          .where(eq(users.stripeCustomerId, customerId));
        console.log(`[Webhook] Assinatura cancelada: créditos zerados para o cliente ${customerId}.`);
        break;
      }

      // Pagamento falhou
      case "invoice.payment_failed": {
        const failedInvoice = event.data.object as Stripe.Invoice;
        const failedCustomerId = failedInvoice.customer as string;

        await db
          .update(users)
          .set({
            subscriptionStatus: "past_due",
            updatedAt: new Date(),
          })
          .where(eq(users.stripeCustomerId, failedCustomerId));
        console.log(`[Webhook] Pagamento falhou: status 'past_due' para o cliente ${failedCustomerId}.`);
        break;
      }
    }
  } catch (error) {
    console.error("Erro ao processar webhook:", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }

  return NextResponse.json({ received: true });
}
