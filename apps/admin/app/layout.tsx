import type { Metadata } from 'next';
import '../../web/app/layout.tsx'; // Import global CSS from web workspace to reuse styling perfectly!

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
      <body className="bg-slate-950 text-slate-100 antialiased font-sans">
        {children}
      </body>
    </html>
  );
}
