import type { Metadata } from "next";
import "./globals.css";

import AuthGate from "@/components/pipelines/AuthGate";

export const metadata: Metadata = {
  title: "Bio Pipeline Manager",
  description: "Design, validate, queue, and run labUtils YAML pipelines.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body suppressHydrationWarning>
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}
