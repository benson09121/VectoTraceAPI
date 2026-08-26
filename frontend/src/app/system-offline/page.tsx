"use client";

import Image from "next/image";
import { Button } from "@/components/ui/button";

export default function SystemOfflinePage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background p-6">
      <div className="flex max-w-md flex-col items-center text-center">
        <Image
          src="/vectotrace-symbol.png"
          alt="VectoTrace"
          width={64}
          height={64}
          className="mb-8 rounded-xl grayscale"
          priority
        />
        <h1 className="mb-3 text-3xl font-semibold tracking-tight">
          Monitoring API unavailable
        </h1>
        <p className="mb-3 text-muted-foreground">
          The dashboard is running, but it cannot reach the VectoTrace API.
          Your session has been preserved.
        </p>
        <p className="mb-8 text-sm text-muted-foreground">
          Start the Django API and its dependencies, then try again. If they
          are already running, verify the frontend API URL and Django CORS
          settings.
        </p>
        <Button type="button" variant="outline" onClick={() => window.location.assign("/")}>
          Try again
        </Button>
      </div>
    </div>
  );
}
