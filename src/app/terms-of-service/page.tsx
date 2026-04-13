import Link from "next/link";

export default function TermsOfServicePage() {
  return (
    <main className="min-h-screen bg-[#030712] text-white px-4 py-20">
      <div className="max-w-4xl mx-auto">
        <div className="mb-10">
          <Link href="/" className="text-sm text-[#d4af37] hover:text-[#f0dfa0] transition-colors">
            ← Voltar para a Home
          </Link>
        </div>

        <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4">Termos de Serviço</h1>
        <p className="text-sm text-gray-400 mb-12">Última atualização: 06 de abril de 2026</p>

        <div className="space-y-10">
          <section>
            <h2 className="text-2xl font-bold mb-3">1. Aceitação dos Termos</h2>
            <p className="text-gray-300 leading-relaxed">
              Ao acessar ou usar a Hive Mind, você concorda com estes Termos de Serviço.
              Se não concordar, não utilize a plataforma.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">2. Objeto do Serviço</h2>
            <p className="text-gray-300 leading-relaxed">
              A Hive Mind fornece mentorias estratégicas com agentes de IA, incluindo sessões
              interativas, transcrição e plano de execução. O serviço não constitui consultoria
              jurídica, contábil ou financeira formal.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">3. Conta e Responsabilidades</h2>
            <ul className="list-disc pl-6 text-gray-300 space-y-2">
              <li>Você é responsável pela veracidade das informações cadastradas.</li>
              <li>Você deve manter credenciais de acesso seguras e confidenciais.</li>
              <li>Uso indevido, fraude ou tentativa de exploração técnica pode gerar bloqueio imediato.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">4. Planos, Pagamento e Cancelamento</h2>
            <p className="text-gray-300 leading-relaxed">
              Planos e preços podem ser atualizados. Assinaturas e cobranças são processadas via Stripe.
              Cancelamentos interrompem renovação futura, mantendo acesso até o fim do ciclo vigente,
              quando aplicável.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">5. Uso Aceitável</h2>
            <ul className="list-disc pl-6 text-gray-300 space-y-2">
              <li>Não enviar conteúdo ilícito, ofensivo ou que viole direitos de terceiros.</li>
              <li>Não tentar engenharia reversa, automação abusiva ou bypass de limites.</li>
              <li>Não utilizar a plataforma para violar leis aplicáveis.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">6. Propriedade Intelectual</h2>
            <p className="text-gray-300 leading-relaxed">
              A marca, software, interface e componentes da Hive Mind são protegidos por direitos
              de propriedade intelectual. O usuário mantém titularidade do conteúdo que envia.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">7. Limitação de Responsabilidade</h2>
            <p className="text-gray-300 leading-relaxed">
              O serviço é fornecido conforme disponibilidade. Recomendamos validação humana antes de
              decisões estratégicas críticas. A Hive Mind não garante resultados comerciais específicos.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">8. Alterações e Encerramento</h2>
            <p className="text-gray-300 leading-relaxed">
              Podemos atualizar estes termos para refletir melhorias e mudanças legais. O uso contínuo
              após atualização representa concordância com a versão vigente.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">9. Contato</h2>
            <p className="text-gray-300 leading-relaxed">
              Dúvidas sobre estes termos podem ser enviadas para{" "}
              <a href="mailto:contato@hivemind.ai" className="text-[#d4af37] hover:text-[#f0dfa0]">
                contato@hivemind.ai
              </a>.
            </p>
          </section>
        </div>
      </div>
    </main>
  );
}
