import { NextRequest, NextResponse } from "next/server";
import { stripe, PLAN_CREDITS } from "@/lib/stripe";
import { db } from "@/lib/db";
import { users } from "@/lib/db/schema";
import { eq } from "drizzle-orm";
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
          // Pagamento avulso - adicionar créditos
          const [user] = await db
            .select()
            .from(users)
            .where(eq(users.id, userId));

          if (user) {
            await db
              .update(users)
              .set({
                credits: (user.credits || 0) + creditsToAdd,
                stripeCustomerId: session.customer as string,
                updatedAt: new Date(),
              })
              .where(eq(users.id, userId));
          }
        } else if (session.mode === "subscription") {
          // Assinatura - atualizar status e créditos
          await db
            .update(users)
            .set({
              subscriptionStatus: "active",
              credits: creditsToAdd,
              stripeCustomerId: session.customer as string,
              updatedAt: new Date(),
            })
            .where(eq(users.id, userId));
        }
        break;
      }

      // Assinatura renovada
      case "invoice.paid": {
        const invoice = event.data.object as Stripe.Invoice;
        const customerId = invoice.customer as string;

        if (invoice.billing_reason === "subscription_cycle") {
          const lineItem = invoice.lines.data[0] as any;
          const priceId = lineItem?.price?.id;
          const creditsToAdd = priceId ? PLAN_CREDITS[priceId] || 0 : 0;

          await db
            .update(users)
            .set({
              credits: creditsToAdd,
              subscriptionStatus: "active",
              updatedAt: new Date(),
            })
            .where(eq(users.stripeCustomerId, customerId));
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
        break;
      }
    }
  } catch (error) {
    console.error("Erro ao processar webhook:", error);
    return NextResponse.json({ error: "Erro interno" }, { status: 500 });
  }

  return NextResponse.json({ received: true });
}
