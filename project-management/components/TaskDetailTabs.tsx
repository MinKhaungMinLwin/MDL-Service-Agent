"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale } from "@/components/LocaleProvider";

type Props = {
  taskId: string;
};

export default function TaskDetailTabs({ taskId }: Props) {
  const pathname = usePathname();
  const { t } = useLocale();
  const base = `/task/${taskId}`;

  const tabs = [
    { href: `${base}/info`, label: t.backlog.tabInfo, key: "info" },
    { href: `${base}/flow`, label: t.backlog.tabFlow, key: "flow" },
    { href: `${base}/review`, label: t.backlog.tabReview, key: "review" },
  ];

  return (
    <nav className="detail-tabs">
      {tabs.map((tab) => (
        <Link
          key={tab.key}
          href={tab.href}
          className={`detail-tab${pathname.startsWith(tab.href) ? " active" : ""}`}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
