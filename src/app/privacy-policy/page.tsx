import Link from "next/link";

export default function PrivacyPolicyPage() {
  return (
    <main className="min-h-screen bg-[#030712] text-white px-4 py-20">
      <div className="max-w-4xl mx-auto">
        <div className="mb-10">
          <Link href="/" className="text-sm text-[#d4af37] hover:text-[#f0dfa0] transition-colors">
            ← Voltar para a Home
          </Link>
        </div>

        <h1 className="text-4xl sm:text-5xl font-black tracking-tight mb-4">Política de Privacidade</h1>
        <p className="text-sm text-gray-400 mb-12">Última atualização: 06 de abril de 2026</p>

        <div className="space-y-10">
          <section>
            <h2 className="text-2xl font-bold mb-3">1. Visão Geral</h2>
            <p className="text-gray-300 leading-relaxed">
              A Hive Mind valoriza sua privacidade. Esta política explica como coletamos,
              usamos, protegemos e compartilhamos informações quando você utiliza a plataforma
              de mentoria executiva com IA.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">2. Dados Coletados</h2>
            <ul className="list-disc pl-6 text-gray-300 space-y-2">
              <li>Dados de conta: nome, e-mail e informações de autenticação.</li>
              <li>Dados de uso: projetos, sessões, transcrições e planos gerados.</li>
              <li>Dados de pagamento: processados pela Stripe, sem armazenamento de cartão pela Hive Mind.</li>
              <li>Dados técnicos: IP, navegador, dispositivo e logs de segurança.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">3. Finalidade do Uso</h2>
            <ul className="list-disc pl-6 text-gray-300 space-y-2">
              <li>Fornecer mentorias, gerar planos de execução e manter histórico de projetos.</li>
              <li>Melhorar performance, qualidade do produto e experiência do usuário.</li>
              <li>Prevenir fraudes, abuso de plataforma e acessos não autorizados.</li>
              <li>Cumprir obrigações legais e regulatórias aplicáveis.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">4. Compartilhamento de Dados</h2>
            <p className="text-gray-300 leading-relaxed">
              Compartilhamos dados apenas com provedores essenciais para operação do serviço,
              como processamento de pagamento, infraestrutura em nuvem e autenticação. Não vendemos
              seus dados pessoais.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">5. Segurança da Informação</h2>
            <p className="text-gray-300 leading-relaxed">
              Aplicamos controles técnicos e organizacionais de segurança, incluindo criptografia em
              trânsito, autenticação e monitoramento. Embora adotemos boas práticas, nenhum sistema é
              100% imune a riscos.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">6. Retenção e Exclusão</h2>
            <p className="text-gray-300 leading-relaxed">
              Mantemos dados pelo período necessário para operação do serviço, cumprimento legal e
              proteção contra fraude. Você pode solicitar atualização ou exclusão de dados através do
              nosso canal de contato.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">7. Direitos do Usuário</h2>
            <p className="text-gray-300 leading-relaxed">
              Você pode solicitar acesso, correção, anonimização, portabilidade e exclusão de dados,
              conforme legislação aplicável, inclusive LGPD quando pertinente.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-bold mb-3">8. Contato</h2>
            <p className="text-gray-300 leading-relaxed">
              Para dúvidas sobre privacidade, fale com a Hive Mind pelo e-mail{" "}
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
