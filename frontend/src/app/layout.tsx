import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-go81-sans',
});

export const metadata: Metadata = {
  title: {
    default: 'Go 81 | Sovereign AI Command Center',
    template: '%s | Go 81',
  },
  description:
    'Go 81 is a local-first AI workspace powered by Ollama, with persistent memory, intelligent workflows, and privacy-focused controls.',
  applicationName: 'Go 81',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="light">
      <body
        className={`${inter.className} ${inter.variable} min-h-screen bg-[#F7F9FC] text-[#152033] antialiased selection:bg-[#DCE6FF] selection:text-[#14213D]`}
      >
        {children}
      </body>
    </html>
  );
}