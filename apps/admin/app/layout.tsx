import type { Metadata } from 'next';
import 'ui/src/styles/globals.css';

export const metadata: Metadata = {
  title: 'smartServe Admin Control & Audit Center',
  description: 'Enterprise Multi-Merchant HITL Approval & APM Telemetry Dashboard',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh">
      <body className="bg-slate-950 text-slate-100 antialiased font-sans">{children}</body>
    </html>
  );
}
