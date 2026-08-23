import type { Metadata } from 'next';
import 'ui/src/styles/globals.css';

export const metadata: Metadata = {
  title: '极光潮品官方旗舰店 - Aurora Luxe Store',
  description: '第三方独立品牌电商商城与智能客服开放对接演示站点',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="bg-slate-50 text-slate-900 font-sans antialiased min-h-screen">{children}</body>
    </html>
  );
}
