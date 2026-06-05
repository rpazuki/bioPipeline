import type { Metadata } from "next";
import "./globals.css";

import AppShell from "@/components/pipelines/AppShell";

export const metadata: Metadata = {
  title: "Bio Pipeline Manager",
  description: "Design, validate, queue, and run labUtils YAML pipelines.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body suppressHydrationWarning>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
