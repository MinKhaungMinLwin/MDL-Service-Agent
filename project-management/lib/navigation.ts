export type SectionId = "overview" | "backlog" | "work" | "wbs" | "issues" | "agents" | "settings";

export type NavItem = { id: string; label: string; href: string };

export type SectionConfig = {
  id: SectionId;
  label: string;
  href: string;
  sidebarTitle: string;
  items: NavItem[];
};

export const OVERVIEW_SLUGS = [
  { slug: "", label: "프로젝트 개요", file: "index" },
  { slug: "domain", label: "도메인 용어", file: "domain" },
  { slug: "pipeline", label: "전체 파이프라인", file: "pipeline" },
  { slug: "modules", label: "서비스 모듈", file: "modules" },
  { slug: "api", label: "API 엔드포인트", file: "api" },
  { slug: "cli", label: "CLI 명령어", file: "cli" },
  { slug: "structure", label: "폴더 구조", file: "structure" },
  { slug: "data", label: "주요 데이터", file: "data" },
  { slug: "tech", label: "기술 스택", file: "tech" },
  { slug: "env", label: "환경 변수", file: "env" },
  { slug: "run", label: "실행 방법", file: "run" },
  { slug: "gaps", label: "알려진 한계", file: "gaps" },
] as const;

export const SECTIONS: Record<SectionId, SectionConfig> = {
  overview: {
    id: "overview",
    label: "Overview",
    href: "/overview",
    sidebarTitle: "프로젝트 문서",
    items: OVERVIEW_SLUGS.map(({ slug, label }) => ({
      id: slug || "overview",
      label,
      href: slug ? `/overview/${slug}` : "/overview",
    })),
  },
  backlog: {
    id: "backlog",
    label: "Task",
    href: "/task",
    sidebarTitle: "IA",
    items: [{ id: "backlog", label: "IA", href: "/task" }],
  },
  work: {
    id: "work",
    label: "Work",
    href: "/work/backlog",
    sidebarTitle: "Work",
    items: [
      { id: "work-backlog", label: "Backlog", href: "/work/backlog" },
      { id: "work-kanban", label: "Kanban", href: "/work/kanban" },
    ],
  },
  wbs: {
    id: "wbs",
    label: "WBS",
    href: "/wbs",
    sidebarTitle: "진행현황",
    items: [{ id: "wbs", label: "WBS", href: "/wbs" }],
  },
  issues: {
    id: "issues",
    label: "Issues",
    href: "/issues",
    sidebarTitle: "Issues",
    items: [{ id: "issues", label: "이슈 목록", href: "/issues" }],
  },
  agents: {
    id: "agents",
    label: "Agent",
    href: "/agents",
    sidebarTitle: "Agent",
    items: [{ id: "agents-list", label: "에이전트 목록", href: "/agents" }],
  },
  settings: {
    id: "settings",
    label: "Settings",
    href: "/settings/users",
    sidebarTitle: "설정",
    items: [{ id: "settings-users", label: "사용자 설정", href: "/settings/users" }],
  },
};

export const TOP_MENUS = [
  SECTIONS.overview,
  SECTIONS.backlog,
  SECTIONS.wbs,
  SECTIONS.issues,
  SECTIONS.work,
  SECTIONS.agents,
];
