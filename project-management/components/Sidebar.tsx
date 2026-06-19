"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale } from "@/components/LocaleProvider";
import { getSidebarConfig } from "@/lib/i18n";
import type { SectionId } from "@/lib/navigation";

type Props = { section: SectionId };

function isActive(pathname: string, href: string): boolean {
  if (href === "/overview") return pathname === "/overview";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function Sidebar({ section }: Props) {
  const pathname = usePathname();
  const { locale } = useLocale();
  const config = getSidebarConfig(locale, section);

  return (
    <aside className="sidebar">
      <div className="sidebar-title">{config.title}</div>
      <nav className="sidebar-nav">
        {config.items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={isActive(pathname, item.href) ? "active" : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
