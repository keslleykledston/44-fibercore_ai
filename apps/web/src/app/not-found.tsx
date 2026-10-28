import Link from "next/link";
export default function NotFound() {
  return <main className="mx-auto grid min-h-screen max-w-md content-center gap-3 px-4"><h1 className="text-2xl font-semibold">Página não encontrada</h1><Link className="text-accent underline" href="/">Voltar ao início</Link></main>;
}
