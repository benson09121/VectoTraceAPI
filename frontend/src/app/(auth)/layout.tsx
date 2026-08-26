import Image from "next/image";
import { ShowcaseModal } from "@/components/showcase-modal";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <ShowcaseModal />
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center text-center">
          <Image
            src="/vectotrace-primary-lockup.png"
            alt="VectoTrace"
            width={180}
            height={40}
            className="dark:invert mb-2"
          />
          <p className="text-sm text-muted-foreground">API monitoring &amp; status</p>
        </div>
        {children}
      </div>
    </main>
  );
}
