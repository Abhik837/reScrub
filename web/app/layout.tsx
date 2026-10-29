import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Newsreader } from "next/font/google";
import "./globals.css";

// Controls and body text.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

// Editorial serif for display headings. "opsz" lets large sizes use the display cut.
const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  axes: ["opsz"],
});

// Timestamps and small uppercase labels only.
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "reScrub · Sterile-technique review",
  description:
    "A training tool for reviewing possible breaks in sterile technique in recorded practice procedures.",
};

// The browser-tab icon comes from app/icon.png (made from the reScrub logo).
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${newsreader.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col bg-canvas text-ink">{children}</body>
    </html>
  );
}
