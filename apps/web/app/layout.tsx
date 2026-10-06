import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { AuthProvider } from "@/components/auth";

// Fonts are bundled (latin subsets from Fontsource 5.3.0, SIL OFL 1.1 — licences in ./fonts), so a build
// never depends on reaching Google Fonts.
const display = localFont({
  src: [{ path: "./fonts/bricolage-grotesque-latin-wght-normal.woff2", weight: "200 800", style: "normal" }],
  variable: "--f-display",
});
const body = localFont({
  src: [
    { path: "./fonts/ibm-plex-sans-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/ibm-plex-sans-latin-500-normal.woff2", weight: "500", style: "normal" },
    { path: "./fonts/ibm-plex-sans-latin-600-normal.woff2", weight: "600", style: "normal" },
  ],
  variable: "--f-body",
});
const mono = localFont({
  src: [
    { path: "./fonts/ibm-plex-mono-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/ibm-plex-mono-latin-500-normal.woff2", weight: "500", style: "normal" },
  ],
  variable: "--f-mono",
});

export const metadata: Metadata = {
  title: { default: "Stackora", template: "%s · Stackora" },
  description: "Hands-on cloud labs with real CLI workflows and instant grading.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
