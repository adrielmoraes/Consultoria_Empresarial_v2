import { NextRequest, NextResponse } from "next/server";
import { stripe, STRIPE_PRICES } from "@/lib/stripe";

export async function POST(request: NextRequest) {
  try {
    const { planId, priceId, userId, userEmail } = await request.json();

    if (!userId) {
      return NextResponse.json({ error: "Dados incompletos" }, { status: 400 });
    }

    const planToPrice: Record<string, string> = {
      session: STRIPE_PRICES.SESSION,
      professional: STRIPE_PRICES.PROFESSIONAL,
    };

    const resolvedPriceId =
      (typeof planId === "string" ? planToPrice[planId] : undefined) ??
      (typeof priceId === "string" ? priceId : undefined);

    if (!resolvedPriceId) {
      return NextResponse.json({ error: "Plano inválido" }, { status: 400 });
    }

    const isSubscription = resolvedPriceId !== STRIPE_PRICES.SESSION;

    const session = await stripe.checkout.sessions.create({
      mode: isSubscription ? "subscription" : "payment",
      payment_method_types: ["card"],
      customer_email: userEmail,
      line_items: [
        {
          price: resolvedPriceId,
          quantity: 1,
        },
      ],
      metadata: {
        userId,
        priceId: resolvedPriceId,
      },
      success_url: `${process.env.NEXTAUTH_URL}/dashboard?success=true&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${process.env.NEXTAUTH_URL}/dashboard?canceled=true`,
    });

    return NextResponse.json({ url: session.url });
  } catch (error) {
    console.error("Erro ao criar sessão de checkout:", error);
    return NextResponse.json(
      { error: "Erro ao processar pagamento" },
      { status: 500 }
    );
  }
}
