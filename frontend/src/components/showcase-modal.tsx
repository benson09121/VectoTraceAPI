"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export function ShowcaseModal() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    // Only show once per session to avoid annoyance
    if (sessionStorage.getItem("showcase_modal_seen")) return;

    api.getSystemConfig().then((config) => {
      if (config.is_showcase_mode) {
        setOpen(true);
        sessionStorage.setItem("showcase_modal_seen", "true");
      }
    });
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Welcome to VectoTrace Showcase!</DialogTitle>
          <DialogDescription className="pt-2">
            The system is currently running in <strong>Showcase Mode</strong>. 
            <br/><br/>
            You don&apos;t need a real email address to sign up or log in. Feel free to use any dummy email you&apos;d like (e.g., <code>demo@example.com</code>). 
            <br/><br/>
            Please note that all demo data is ephemeral and will be wiped every 24 hours.
          </DialogDescription>
        </DialogHeader>
        <div className="flex justify-end pt-2">
          <Button onClick={() => setOpen(false)}>I understand</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
