import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Opscend — know why the deploy broke", template: "%s · Opscend" },
  description:
    "Open-source, self-hosted deploy investigator. One timeline for Vercel, Railway and GitHub, and a read-only AI that names the commit that broke it — with evidence.",
};

export const viewport: Viewport = {
  themeColor: "#0f0f0e",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
