#!/usr/bin/env python3
"""Migrate legacy HTML content to locale markdown files."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGACY_OVERVIEW = ROOT / "content" / "overview"
LEGACY_WBS = ROOT / "content" / "wbs.html"
KO_DIR = ROOT / "content" / "ko"
EN_DIR = ROOT / "content" / "en"

# Minimal EN translations for page titles / headers (HTML blocks)
EN_TITLE_MAP = {
    "프로젝트 개요": "Project Overview",
    "도메인 용어": "Domain Terms",
    "전체 파이프라인": "Pipeline",
    "서비스 모듈": "Service Modules",
    "API 엔드포인트": "API Endpoints",
    "CLI 명령어": "CLI Commands",
    "폴더 구조": "Folder Structure",
    "주요 데이터": "Key Data",
    "기술 스택": "Tech Stack",
    "환경 변수": "Environment Variables",
    "실행 방법": "How to Run",
    "알려진 한계": "Known Limitations",
    "진행현황 (WBS)": "Progress (WBS)",
    "IA": "IA",
    "Issues": "Issues",
    "WBS 일정표": "WBS Schedule",
    "범례": "Legend",
    "완료": "Done",
    "진행 중": "In Progress",
    "진행 예정": "Planned",
    "구분": "Category",
    "세부 업무": "Task",
    "진행상태": "Status",
    "전체 진행률": "Overall Progress",
    "업무 IA 트리": "Work IA Tree",
    "전체 업무 목록": "All Tasks",
}


def html_to_md_wrapper(html: str) -> str:
    """Wrap HTML fragment for markdown (rendered via rehype-raw)."""
    html = html.strip()
    if not html:
        return ""
    return f"<!-- html -->\n\n{html}\n"


def translate_html_en(html: str) -> str:
    out = html
    for ko, en in sorted(EN_TITLE_MAP.items(), key=lambda x: -len(x[0])):
        out = out.replace(ko, en)
    # Common phrases
    replacements = [
        ("CCPP EPC 프로젝트의 MDL(Master Document List)을 자동 생성하는 시스템입니다.",
         "A system that automatically generates MDL (Master Document List) for CCPP EPC projects."),
        ("과제 2: MDL 생성 및 L3 일정 비교 모델 개발",
         "Task 2: MDL generation and L3 schedule comparison model development"),
        ("* 진행률은 각 과제의 전체 대비 완료 업무 비율이며, 각 과제의 WBS를 기준으로 완료 및 미완료 항목을 반영해 산출",
         "* Progress is calculated from completed vs. total tasks per assignment, based on each WBS."),
        ("* 진행 상태에 따른 색상 안내:", "* Color guide by status:"),
        ("- 완료 : 파란색", "- Done: blue"),
        ("- 진행 중: 초록색", "- In progress: green"),
        ("- 진행 예정: 회색", "- Planned: gray"),
        ("업무 정보구조 — 구분 › 중분류 › 세부 업무 계층",
         "Work structure — Category › Subcategory › Task hierarchy"),
        ("프로젝트 이슈·리스크·블로커를 추적합니다.",
         "Track project issues, risks, and blockers."),
    ]
    for ko, en in replacements:
        out = out.replace(ko, en)
    return out


def write_ia_issues_ko():
    ia = """<!-- html -->
<header class="page-header">
  <h1>IA</h1>
  <p>업무 정보구조 — 구분 › 중분류 › 세부 업무 계층</p>
</header>

<section>
  <div class="alert alert-info">
    <strong>범례</strong> —
    <span class="status-badge status-done">완료</span>
    <span class="status-badge status-progress">진행중</span>
    <span class="status-badge status-todo">진행예정</span>
  </div>
</section>
"""
    issues = """<!-- html -->
<header class="page-header">
  <h1>Issues</h1>
  <p>프로젝트 이슈·리스크·블로커를 추적합니다.</p>
</header>
"""
    (KO_DIR / "ia.md").write_text(ia, encoding="utf-8")
    (EN_DIR / "ia.md").write_text(translate_html_en(ia), encoding="utf-8")
    (KO_DIR / "issues.md").write_text(issues, encoding="utf-8")
    (EN_DIR / "issues.md").write_text(translate_html_en(issues), encoding="utf-8")


def main():
    if KO_DIR.exists():
        shutil.rmtree(KO_DIR)
    if EN_DIR.exists():
        shutil.rmtree(EN_DIR)
    (KO_DIR / "overview").mkdir(parents=True)
    (EN_DIR / "overview").mkdir(parents=True)

    if LEGACY_OVERVIEW.exists():
        for html_file in sorted(LEGACY_OVERVIEW.glob("*.html")):
            html = html_file.read_text(encoding="utf-8")
            md = html_to_md_wrapper(html)
            name = html_file.stem + ".md"
            (KO_DIR / "overview" / name).write_text(md, encoding="utf-8")
            (EN_DIR / "overview" / name).write_text(html_to_md_wrapper(translate_html_en(html)), encoding="utf-8")

    if LEGACY_WBS.exists():
        html = LEGACY_WBS.read_text(encoding="utf-8")
        (KO_DIR / "wbs.md").write_text(html_to_md_wrapper(html), encoding="utf-8")
        (EN_DIR / "wbs.md").write_text(html_to_md_wrapper(translate_html_en(html)), encoding="utf-8")

    write_ia_issues_ko()
    print(f"Migrated to {KO_DIR} and {EN_DIR}")


if __name__ == "__main__":
    main()
