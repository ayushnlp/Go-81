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
    default: 'Go 81 | Autonomous AI Agent Command Center',
    template: '%s | Go 81',
  },
  description:
    'Go 81 is a desktop-first sovereign AI agent command center powered by Ollama, with encrypted memory, transparent security gates, and local autonomy.',
  applicationName: 'Go 81',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                const storedTheme = localStorage.getItem('go81_theme');
                if (storedTheme) {
                  document.documentElement.setAttribute('data-theme', storedTheme);
                } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
                  document.documentElement.setAttribute('data-theme', 'light');
                } else {
                  document.documentElement.setAttribute('data-theme', 'dark');
                }
              } catch (e) {}
            `,
          }}
        />
      </head>
      <body
        className={`${inter.className} ${inter.variable} min-h-screen antialiased selection:bg-[#ea580c] selection:text-white`}
      >
        {children}
      </body>
    </html>
  );
}
