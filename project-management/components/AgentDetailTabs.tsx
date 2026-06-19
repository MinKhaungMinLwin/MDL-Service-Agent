"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale } from "@/components/LocaleProvider";

type Props = {
  agentId: string;
};

export default function AgentDetailTabs({ agentId }: Props) {
  const pathname = usePathname();
  const { t } = useLocale();
  const base = `/agents/${agentId}`;

  const tabs = [
    { href: `${base}/logic`, label: t.agents.tabLogic, key: "logic" },
    { href: `${base}/flow`, label: t.agents.tabFlow, key: "flow" },
    { href: `${base}/playground`, label: t.agents.tabPlayground, key: "playground" },
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
