const SECTIONS = {
  overview: {
    label: "Overview",
    href: "../overview/index.html",
    sidebarTitle: "프로젝트 문서",
    items: [
      { id: "overview",  label: "프로젝트 개요",   href: "index.html" },
      { id: "domain",    label: "도메인 용어",     href: "domain.html" },
      { id: "pipeline",  label: "전체 파이프라인", href: "pipeline.html" },
      { id: "modules",   label: "서비스 모듈",     href: "modules.html" },
      { id: "api",       label: "API 엔드포인트",  href: "api.html" },
      { id: "cli",       label: "CLI 명령어",      href: "cli.html" },
      { id: "structure", label: "폴더 구조",       href: "structure.html" },
      { id: "data",      label: "주요 데이터",     href: "data.html" },
      { id: "tech",      label: "기술 스택",       href: "tech.html" },
      { id: "env",       label: "환경 변수",       href: "env.html" },
      { id: "run",       label: "실행 방법",       href: "run.html" },
      { id: "gaps",      label: "알려진 한계",     href: "gaps.html" },
    ],
  },
  backlog: {
    label: "Backlog",
    href: "../backlog/ia.html",
    sidebarTitle: "Backlog",
    items: [
      { id: "ia", label: "IA (정보구조)", href: "ia.html" },
    ],
  },
  issues: {
    label: "Issues",
    href: "../issues/index.html",
    sidebarTitle: "Issues",
    items: [
      { id: "index", label: "이슈 목록", href: "index.html" },
    ],
  },
  wbs: {
    label: "진행현황(WBS)",
    href: "../wbs/index.html",
    sidebarTitle: "진행현황",
    items: [
      { id: "index", label: "WBS 진행현황", href: "index.html" },
    ],
  },
};

const TOP_MENUS = [
  { id: "overview", label: "Overview", href: "../overview/index.html" },
  { id: "backlog",  label: "Backlog", href: "../backlog/ia.html" },
  { id: "wbs",      label: "진행현황(WBS)", href: "../wbs/index.html" },
  { id: "issues",   label: "Issues", href: "../issues/index.html" },
];

function renderHeader() {
  const header = document.getElementById("site-header");
  if (!header) return;

  const currentSection = document.body.dataset.section || "";

  const menuHtml = TOP_MENUS.map(
    (menu) =>
      `<a href="${menu.href}" class="nav-link${menu.id === currentSection ? " active" : ""}">${menu.label}</a>`
  ).join("");

  header.className = "site-header";
  header.innerHTML = `
    <div class="header-inner">
      <div class="header-brand">
        <a href="../overview/index.html">Doosan MDL</a>
      </div>
      <nav class="header-nav">${menuHtml}</nav>
      <div class="header-meta">phase2-initial · v0.1.0</div>
    </div>`;
}

function renderSidebar() {
  const sidebar = document.getElementById("sidebar");
  if (!sidebar) return;

  const currentSection = document.body.dataset.section || "";
  const currentPage = document.body.dataset.page || "";
  const section = SECTIONS[currentSection];
  if (!section) return;

  const links = section.items
    .map(
      (item) =>
        `<a href="${item.href}" class="${item.id === currentPage ? "active" : ""}">${item.label}</a>`
    )
    .join("");

  sidebar.className = "sidebar";
  sidebar.innerHTML = `
    <div class="sidebar-title">${section.sidebarTitle}</div>
    <nav class="sidebar-nav">${links}</nav>`;
}

document.addEventListener("DOMContentLoaded", () => {
  renderHeader();
  renderSidebar();
});
