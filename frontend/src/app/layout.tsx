import type { Metadata } from "next";
import { Fira_Sans, Fira_Code } from "next/font/google";
import "./globals.css";

// Fira Sans for UI copy; Fira Code for anything read character by character —
// URLs, tokens, status codes, latencies.
const firaSans = Fira_Sans({
  variable: "--font-fira-sans",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
});

const firaCode = Fira_Code({
  variable: "--font-fira-code",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "VectoTrace — Self-hosted uptime monitoring",
  description:
    "Monitor HTTP, DNS, ports, certificates and cron jobs. Alert to 200+ services. Publish a status page. Run it all yourself.",
  icons: {
    icon: "/favicon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      // suppressHydrationWarning: the inline script below sets `class="dark"`
      // before paint, so the server-rendered html element legitimately differs
      // from the client's.
      suppressHydrationWarning
      className={`${firaSans.variable} ${firaCode.variable} h-full antialiased`}
    >
      <head>
        {/*
          Resolve the theme before first paint. Without this the page renders
          light, then snaps to dark once React hydrates — a flash that looks
          broken on every single navigation for dark-mode users.
        */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('vt-theme')||'system';var d=t==='dark'||(t==='system'&&matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.classList.toggle('dark',d);}catch(e){}})();`,
          }}
        />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
