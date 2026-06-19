"use client";

import { useEffect, useState } from "react";
import { useLocale } from "@/components/LocaleProvider";
import MarkdownContent from "@/components/MarkdownContent";
import type { Locale } from "@/lib/i18n";

type Props = {
  contentPath: string;
  initial?: Partial<Record<Locale, string>>;
};

export default function ContentPage({ contentPath, initial }: Props) {
  const { locale } = useLocale();
  const [source, setSource] = useState(() => initial?.[locale] ?? initial?.ko ?? "");
  const [activeLocale, setActiveLocale] = useState(locale);

  useEffect(() => {
    const cached = initial?.[locale];
    if (cached) {
      setSource(cached);
      setActiveLocale(locale);
      return;
    }
    setSource("");
    fetch(`/api/content/${locale}/${contentPath}`)
      .then((r) => (r.ok ? r.text() : fetch(`/api/content/ko/${contentPath}`).then((r) => r.text())))
      .then((text) => {
        setSource(text);
        setActiveLocale(locale);
      })
      .catch(() => setSource(""));
  }, [locale, contentPath, initial]);

  if (!source || activeLocale !== locale) {
    return <div className="content-loading">{locale === "en" ? "Loading…" : "불러오는 중…"}</div>;
  }

  return <MarkdownContent key={`${locale}-${contentPath}`} source={source} />;
}
