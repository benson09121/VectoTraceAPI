"use client";

/**
 * Landing page.
 *
 * Structure follows the "Real-Time / Operations" pattern: hero with a live
 * preview, the numbers that matter, how it works, then the call to action.
 * Ops buyers want proof before prose, so the hero shows the actual product
 * component (the heartbeat strip) rather than a stock illustration.
 *
 * Design rules from DESIGN.md apply here too — same tokens, same fonts, same
 * motion budget. The marketing page is allowed to breathe more than the
 * dashboard, but it is not allowed to look like a different product.
 */

import Link from "next/link";
import Image from "next/image";
import { motion, MotionConfig } from "motion/react";
import {
  ArrowRight,
  Bell,
  ChartLine,
  CheckCircle,
  Clock,
  Cube,
  GithubLogo,
  Lock,
  Pulse,
} from "@phosphor-icons/react";
import { HeartbeatBar, type Beat } from "@/components/heartbeat-bar";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/shell";

/**
 * A fixed, obviously-illustrative sample. Deterministic rather than random so
 * the page renders identically on server and client — a random series would
 * hydrate mismatched — and so it never accidentally implies real uptime data.
 */
const SAMPLE: Beat[] = Array.from({ length: 40 }, (_, i) => ({
  result: i === 11 || i === 12 ? ("failure" as const) : ("success" as const),
  response_time_ms: 60 + ((i * 17) % 90),
  checked_at: new Date(Date.UTC(2026, 0, 1, 0, i)).toISOString(),
}));

const MONITOR_TYPES = [
  "HTTP(S)",
  "Keyword",
  "JSON query",
  "Ping",
  "TCP port",
  "DNS record",
  "SSL certificate",
  "Domain expiry",
  "Heartbeat",
];

const FEATURES = [
  {
    icon: Pulse,
    title: "Nine monitor types",
    body: "Monitor more than HTTP. A service can be reachable while its content, JSON response, certificate, DNS record, TCP port, domain, or scheduled job is unhealthy. Checked as often as every 20 seconds.",
  },
  {
    icon: Bell,
    title: "200+ notification services",
    body: "Powered by Apprise: Slack, Discord, Telegram, Matrix, ntfy, Teams, PagerDuty, SMS, email and roughly two hundred more. Unified response and communication out of the box.",
  },
  {
    icon: ChartLine,
    title: "Make latency actionable",
    body: "Every HTTP check records DNS, connect, TLS handshake, time-to-first-byte, and total response time. “Your site is slow” is not actionable; “DNS took 800ms” is.",
  },
  {
    icon: Clock,
    title: "Reduce alert noise",
    body: "An incident opens after three consecutive failures and automatically resolves after five consecutive successful recovery checks. Maintenance windows suppress noise during planned work.",
  },
  {
    icon: Lock,
    title: "Status communication",
    body: "Public or password-protected status pages with light, dark, or automatic themes. Verified email or webhook subscriptions. Keep customers informed automatically.",
  },
  {
    icon: Cube,
    title: "Self-hosted, end to end",
    body: "Own the operational data. Check history, incidents, subscribers, and alert configuration remain in infrastructure you control. Docker makes deployment portable.",
  },
];

const STEPS = [
  {
    n: "01",
    title: "Point it at something",
    body: "Add a URL, host, port or domain. Pick an interval from 20 seconds upward and what counts as healthy.",
  },
  {
    n: "02",
    title: "Connect a channel",
    body: "Paste a webhook or an Apprise URL. Send a test message and confirm it lands before you rely on it.",
  },
  {
    n: "03",
    title: "Publish a status page",
    body: "Attach monitors, choose a slug, and share it. Subscribers are notified automatically when incidents open and resolve.",
  },
];

const FADE_UP = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const STAGGER = {
  animate: { transition: { staggerChildren: 0.05 } },
};

function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 sm:px-6">
        <Link href="/" className="flex items-center tracking-tight transition-opacity hover:opacity-80">
          <Image 
            src="/vectotrace-primary-lockup.png" 
            alt="VectoTrace Logo" 
            width={180} 
            height={40} 
            className="h-8 w-auto rounded-sm object-contain"
          />
        </Link>
        <nav className="ml-auto flex items-center gap-1 sm:gap-2" aria-label="Primary">
          <ThemeToggle />
          <Button asChild variant="ghost" size="sm" className="cursor-pointer">
            <Link href="/login">Sign in</Link>
          </Button>
          {/* Primary CTA in the nav, per the operations landing pattern. */}
          <Button asChild size="sm" className="cursor-pointer">
            <Link href="/register">Get started</Link>
          </Button>
        </nav>
      </div>
    </header>
  );
}

export default function LandingPage() {
  return (
    <MotionConfig reducedMotion="user" transition={{ duration: 0.4, ease: [0.215, 0.61, 0.355, 1] }}>
      <Nav />

      <main className="flex-1">
        {/* ---------------------------------------------------------------- */}
        {/* Hero: product claim + live preview                                */}
        {/* ---------------------------------------------------------------- */}
        <section className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-2 lg:items-center lg:py-24 overflow-hidden">
          <motion.div 
            className="flex flex-col gap-6"
            initial="initial"
            animate="animate"
            variants={STAGGER}
          >
            <motion.span variants={FADE_UP} className="w-fit rounded-full border border-border bg-muted px-3 py-1 text-xs font-medium flex items-center gap-2">
              <Image src="/vectotrace-symbol.png" alt="Icon" width={16} height={16} className="rounded-sm" />
              Open source · Self-hosted
            </motion.span>
            <motion.h1 variants={FADE_UP} className="text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
              Know when it fails.
              <br />
              Explain what happened next.
            </motion.h1>
            <motion.p variants={FADE_UP} className="max-w-prose text-lg text-muted-foreground">
              Self-hosted uptime monitoring, incident response, alerting, and public status pages for teams. VectoTrace watches your infrastructure, schedules checks, records response timing, and publishes service health — all from your own environment.
            </motion.p>
            <motion.div variants={FADE_UP} className="flex flex-wrap gap-3">
              <Button asChild size="lg" className="cursor-pointer">
                <Link href="/register">
                  Start monitoring
                  <ArrowRight className="size-4" aria-hidden />
                </Link>
              </Button>
              <Button asChild size="lg" variant="outline" className="cursor-pointer">
                <Link href="/login">Sign in</Link>
              </Button>
            </motion.div>
            <motion.ul variants={FADE_UP} className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted-foreground">
              {["Own the operational data", "Reduce alert noise", "MIT licensed"].map((t) => (
                <li key={t} className="flex items-center gap-1.5">
                  <CheckCircle className="size-4 text-up" weight="fill" aria-hidden />
                  {t}
                </li>
              ))}
            </motion.ul>
          </motion.div>

          {/* Live preview: the real dashboard component, with sample data. */}
          <motion.div 
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.6, ease: [0.165, 0.84, 0.44, 1], delay: 0.2 }}
            className="rounded-xl border border-border bg-card p-5 shadow-sm"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-semibold">Payments API</p>
                <p className="truncate font-mono text-xs text-muted-foreground">
                  https://api.example.com/health
                </p>
              </div>
              <span className="shrink-0 rounded-lg bg-up px-3 py-1.5 text-sm font-semibold text-white">
                Up
              </span>
            </div>

            <div className="mt-5">
              <HeartbeatBar beats={SAMPLE} slots={40} showScale />
              <p className="mt-2 text-xs text-muted-foreground">
                Checks every 20 seconds
              </p>
            </div>

            <div className="mt-5 grid grid-cols-3 divide-x divide-border border-t border-border pt-4">
              {[
                { l: "Response", v: "57 ms" },
                { l: "Uptime 24h", v: "99.98%" },
                { l: "p95", v: "142 ms" },
              ].map((m) => (
                <div key={m.l} className="px-2 text-center">
                  <p className="text-xs text-muted-foreground">{m.l}</p>
                  <p className="mt-0.5 font-semibold tabular">{m.v}</p>
                </div>
              ))}
            </div>
            <p className="mt-4 text-center text-xs text-muted-foreground">
              Sample data — this is the real dashboard component.
            </p>
          </motion.div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Key indicators                                                    */}
        {/* ---------------------------------------------------------------- */}
        <section className="border-y border-border bg-card overflow-hidden">
          <motion.div 
            initial="initial"
            whileInView="animate"
            viewport={{ once: true, margin: "-100px" }}
            variants={STAGGER}
            className="mx-auto grid max-w-6xl grid-cols-2 gap-6 px-4 py-10 sm:px-6 lg:grid-cols-4"
          >
            {[
              { v: "20s", l: "Minimum check interval" },
              { v: "9", l: "Monitor types" },
              { v: "200+", l: "Notification services" },
              { v: "100%", l: "Self-hosted" },
            ].map((s) => (
              <motion.div variants={FADE_UP} key={s.l} className="text-center">
                <p className="text-3xl font-semibold text-primary">{s.v}</p>
                <p className="mt-1 text-sm text-muted-foreground">{s.l}</p>
              </motion.div>
            ))}
          </motion.div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Features                                                          */}
        {/* ---------------------------------------------------------------- */}
        <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:py-20 overflow-hidden">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-100px" }}
          >
            <h2 className="text-2xl font-semibold tracking-tight flex items-center gap-3">
              <Image src="/vectotrace-symbol.png" alt="Icon" width={32} height={32} className="rounded-md" />
              Everything you need to run monitoring yourself
            </h2>
            <p className="mt-2 max-w-prose text-muted-foreground">
              Built for the person who gets paged, not the person who buys the
              software.
            </p>
          </motion.div>

          <motion.div 
            initial="initial"
            whileInView="animate"
            viewport={{ once: true, margin: "-100px" }}
            variants={STAGGER}
            className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
          >
            {FEATURES.map(({ icon: Icon, title, body }) => (
              <motion.div
                variants={FADE_UP}
                key={title}
                className="flex flex-col gap-2 rounded-lg border border-border bg-card p-5 hover:border-primary/50 transition-colors"
              >
                <Icon className="size-5 text-primary" aria-hidden />
                <h3 className="font-semibold">{title}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
              </motion.div>
            ))}
          </motion.div>

          <motion.div 
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true }}
            transition={{ delay: 0.3 }}
            className="mt-6 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/40 p-4"
          >
            <span className="text-sm font-medium">Monitor types:</span>
            {MONITOR_TYPES.map((t) => (
              <span
                key={t}
                className="rounded-full border border-border bg-card px-2.5 py-0.5 text-xs"
              >
                {t}
              </span>
            ))}
          </motion.div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* How it works                                                      */}
        {/* ---------------------------------------------------------------- */}
        <section className="border-t border-border bg-card overflow-hidden">
          <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:py-20">
            <motion.h2 
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true, margin: "-100px" }}
              className="text-2xl font-semibold tracking-tight"
            >
              Running in three steps
            </motion.h2>
            <motion.div 
              initial="initial"
              whileInView="animate"
              viewport={{ once: true, margin: "-100px" }}
              variants={STAGGER}
              className="mt-8 grid gap-6 md:grid-cols-3"
            >
              {STEPS.map((s) => (
                <motion.div variants={FADE_UP} key={s.n} className="flex flex-col gap-2">
                  <span className="font-mono text-sm font-semibold text-primary">
                    {s.n}
                  </span>
                  <h3 className="font-semibold">{s.title}</h3>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    {s.body}
                  </p>
                </motion.div>
              ))}
            </motion.div>

          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Closing CTA                                                       */}
        {/* ---------------------------------------------------------------- */}
        <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
          <motion.div 
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-50px" }}
            transition={{ ease: [0.215, 0.61, 0.355, 1], duration: 0.6 }}
            className="flex flex-col items-center gap-5 rounded-xl border border-border bg-card px-6 py-12 text-center shadow-lg"
          >
            <Image src="/vectotrace-symbol.png" alt="VectoTrace Symbol" width={48} height={48} className="rounded-xl shadow-sm mb-2" />
            <h2 className="max-w-lg text-2xl font-semibold tracking-tight sm:text-3xl">
              Set up your first monitor in under a minute
            </h2>
            <p className="max-w-prose text-muted-foreground">
              Create an organization, point it at an endpoint, and connect a
              notification channel. Nothing else to configure.
            </p>
            <Button asChild size="lg" className="cursor-pointer shadow-sm group">
              <Link href="/register">
                Get started
                <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
              </Link>
            </Button>
          </motion.div>
        </section>
      </main>

      <footer className="border-t border-border bg-card">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-3 px-4 py-8 text-sm text-muted-foreground sm:flex-row sm:px-6">
          <p className="flex items-center gap-2">
            <Image src="/vectotrace-symbol.png" alt="VectoTrace Symbol" width={20} height={20} className="h-5 w-auto rounded-sm grayscale opacity-70" />
            VectoTrace — self-hosted uptime monitoring
          </p>
          <div className="flex items-center gap-4 sm:ml-auto">
            <Link href="/login" className="transition-colors hover:text-foreground">
              Sign in
            </Link>
            <a
              href="https://github.com/your-org/vectotrace"
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 transition-colors hover:text-foreground"
            >
              <GithubLogo className="size-4" aria-hidden />
              Source
            </a>
          </div>
        </div>
      </footer>
    </MotionConfig>
  );
}
