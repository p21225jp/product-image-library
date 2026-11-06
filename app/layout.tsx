import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MKT团队素材空间",
  description: "按产品 SKU、名称和图片属性准确查找团队素材。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
