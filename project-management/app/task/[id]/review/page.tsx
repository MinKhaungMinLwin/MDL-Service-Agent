"use client";

import { useLocale } from "@/components/LocaleProvider";

export default function TaskReviewPage() {
  const { t } = useLocale();

  return (
    <section className="detail-placeholder">
      <p>{t.backlog.reviewPlaceholder}</p>
    </section>
  );
}
