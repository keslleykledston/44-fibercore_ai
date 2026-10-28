import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "FiberCore", description: "Gerenciamento de OLT/ONU para provedores" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="pt-BR" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: "try{var t=localStorage.getItem('fc-theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t)}catch(e){}" }} /></head>
      <body>{children}</body>
    </html>;
}
