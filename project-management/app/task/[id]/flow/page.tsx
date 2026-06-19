"use client";

import { useLocale } from "@/components/LocaleProvider";

export default function TaskFlowPage() {
  const { t } = useLocale();

  return (
    <section className="detail-placeholder">
      <p>{t.backlog.flowPlaceholder}</p>
    </section>
  );
}
