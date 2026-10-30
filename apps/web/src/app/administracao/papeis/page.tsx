import { redirect } from "next/navigation";

/** Papéis e permissões agora é a aba "Funções" de Equipe e acessos. */
export default function Papeis() {
  redirect("/administracao/equipe?aba=funcoes");
}
