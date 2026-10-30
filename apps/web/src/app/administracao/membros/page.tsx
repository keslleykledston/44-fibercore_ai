import { redirect } from "next/navigation";

/** A área de membros virou "Equipe e acessos" (um só lugar para convidar, mudar função, redefinir e remover). */
export default function Membros() {
  redirect("/administracao/equipe");
}
