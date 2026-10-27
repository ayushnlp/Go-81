import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Go 81 | Sovereign AI Command Center',
  description:
    'A sovereign, always-on personal AI agent running on local Ollama stack with persistent memory, multi-step task execution, registered skills, and privacy controls.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#090b0e] text-zinc-100 antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
