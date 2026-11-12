import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export const metadata: Metadata = { title: "FiberCore", description: "Gerenciamento de OLT/ONU para provedores" };

// Ler `x-nonce` (colocado pelo middleware, ADR-0042) torna TODAS as páginas dinâmicas: o HTML é renderizado por requisição, com um nonce novo.
// Sem isso o Next prerenderizaria páginas estáticas com scripts sem nonce. Os estáticos de `/_next/static` continuam cacheáveis.
export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return <html lang="pt-BR" suppressHydrationWarning>
      <head><script nonce={nonce} dangerouslySetInnerHTML={{ __html: "try{var t=localStorage.getItem('fc-theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t)}catch(e){}" }} /></head>
      <body>{children}</body>
    </html>;
}
