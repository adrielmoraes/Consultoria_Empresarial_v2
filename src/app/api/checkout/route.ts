import { NextRequest, NextResponse } from "next/server";
import { stripe, STRIPE_PRICES } from "@/lib/stripe";
import { auth } from "@/auth";

export async function POST(request: NextRequest) {
  try {
    // SEGURANÇA: userId e email extraídos da sessão autenticada do servidor.
    // Impede que um hacker pague com seu cartão mas credite outro userId.
    const session = await auth();

    if (!session?.user?.id) {
      return NextResponse.json(
        { error: "Não autenticado. Faça login para continuar." },
        { status: 401 }
      );
    }

    const userId = session.user.id;
    const userEmail = session.user.email || undefined;

    const { planId, priceId } = await request.json();

    // Mapeamento de planId → price real da Stripe
    // Ambos os planos são assinaturas mensais recorrentes (modelo High Ticket)
    const planToPrice: Record<string, string> = {
      session:      STRIPE_PRICES.SESSION,      // Executivo   — R$497,90/mês
      professional: STRIPE_PRICES.PROFESSIONAL, // Profissional — R$1.197,90/mês
    };

    const resolvedPriceId =
      (typeof planId === "string" ? planToPrice[planId] : undefined) ??
      (typeof priceId === "string" ? priceId : undefined);

    if (!resolvedPriceId) {
      return NextResponse.json({ error: "Plano inválido" }, { status: 400 });
    }

    const origin =
      request.headers.get("origin") ||
      request.nextUrl.origin ||
      process.env.NEXT_PUBLIC_APP_URL ||
      "http://localhost:3000";

    // Ambos os planos são subscription — o modelo de pagamento avulso não existe mais
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      payment_method_types: ["card"],
      customer_email: userEmail || undefined,
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
      subscription_data: {
        metadata: {
          userId,
          priceId: resolvedPriceId,
        },
      },
      success_url: `${origin}/dashboard/subscription?success=true&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${origin}/dashboard/subscription?canceled=true`,
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
