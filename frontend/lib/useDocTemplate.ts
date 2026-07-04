"use client";

// Fetches /api/templates/{docId} once per doc switch. Owned by the page
// (not the preview component) because the manifest inside the response
// also drives the manual-edit form tab and download gating up in the
// header — the preview is just one consumer.

import { useEffect, useState } from "react";
import { ApiError, templatesApi, type TemplateResponse } from "@/lib/api";

export type TemplateLoad =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; template: TemplateResponse }
  | { kind: "error"; message: string };

export function useDocTemplate(
  docId: string,
  enabled: boolean,
  fallbackError: string,
): TemplateLoad {
  const [load, setLoad] = useState<TemplateLoad>({ kind: "idle" });

  useEffect(() => {
    if (!enabled) {
      setLoad({ kind: "idle" });
      return;
    }
    let cancelled = false;
    setLoad({ kind: "loading" });
    templatesApi
      .get(docId)
      .then((template) => {
        if (!cancelled) setLoad({ kind: "ready", template });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof ApiError && err.message ? err.message : fallbackError;
        setLoad({ kind: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [docId, enabled, fallbackError]);

  return load;
}
