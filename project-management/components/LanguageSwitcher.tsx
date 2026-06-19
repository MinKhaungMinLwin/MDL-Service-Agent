"use client";

import { useEffect, useRef, useState } from "react";
import { LOCALES, type Locale } from "@/lib/i18n";
import { useLocale } from "@/components/LocaleProvider";

export default function LanguageSwitcher() {
  const { locale, setLocale } = useLocale();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const current = LOCALES.find((l) => l.id === locale) ?? LOCALES[0];

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  function select(id: Locale) {
    setLocale(id);
    setOpen(false);
  }

  return (
    <div className="lang-dropdown" ref={ref}>
      <button
        type="button"
        className="lang-dropdown-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {current.label}
        <span className="lang-dropdown-chevron" aria-hidden="true">
          ▾
        </span>
      </button>
      {open && (
        <ul className="lang-dropdown-menu" role="listbox" aria-label="Language">
          {LOCALES.map(({ id, label }) => (
            <li key={id} role="option" aria-selected={locale === id}>
              <button
                type="button"
                className={`lang-dropdown-item${locale === id ? " active" : ""}`}
                onClick={() => select(id)}
              >
                {label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
