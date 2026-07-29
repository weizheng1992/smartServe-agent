import type { Metadata } from 'next';
import 'ui/src/styles/globals.css';

export const metadata: Metadata = {
  title: 'AI Agent Support Center',
  description: 'AI Customer Support Agent Platform',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
