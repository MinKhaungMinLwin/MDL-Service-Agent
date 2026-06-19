"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import SettingsMenu from "@/components/SettingsMenu";
import { useLocale } from "@/components/LocaleProvider";
import { getNavLabel } from "@/lib/i18n";
import { TOP_MENUS, type SectionId } from "@/lib/navigation";

function activeSection(pathname: string): SectionId | "" {
  if (pathname.startsWith("/overview")) return "overview";
  if (pathname.startsWith("/task") || pathname.startsWith("/backlog")) return "backlog";
  if (pathname.startsWith("/work")) return "work";
  if (pathname.startsWith("/wbs")) return "wbs";
  if (pathname.startsWith("/issues")) return "issues";
  if (pathname.startsWith("/agents")) return "agents";
  if (pathname.startsWith("/settings")) return "settings";
  return "";
}

export default function Header() {
  const pathname = usePathname();
  const current = activeSection(pathname);
  const { locale } = useLocale();

  return (
    <header className="site-header">
      <div className="header-inner">
        <div className="header-brand">
          <Link href="/overview">Doosan MDL</Link>
        </div>
        <nav className="header-nav">
          {TOP_MENUS.map((menu) => (
            <Link
              key={menu.id}
              href={menu.href}
              className={`nav-link${current === menu.id ? " active" : ""}`}
            >
              {getNavLabel(locale, menu.id)}
            </Link>
          ))}
        </nav>
        <div className="header-actions">
          <SettingsMenu />
          <LanguageSwitcher />
        </div>
      </div>
    </header>
  );
}
