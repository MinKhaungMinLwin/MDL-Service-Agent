# PM Project Management

PM 전용 대시보드(Next.js)입니다. 개발 코드(`src/` 등)와 분리해 관리합니다.

## 브랜치 규칙

| 브랜치 | 용도 |
|--------|------|
| `phase2-initial` | 팀 통합 브랜치 (기본) |
| `pm/project-management` | PM 전용 작업 브랜치 |

## PM 작업 흐름

```bash
# 1. 최신 통합 브랜치 동기화
git checkout phase2-initial
git pull origin phase2-initial

# 2. PM 브랜치로 이동
git checkout pm/project-management

# 3. 통합 브랜치 변경 반영 (주기적으로)
git merge phase2-initial

# 4. project-management/ 수정 후 커밋
git add project-management/
git commit -m "docs(pm): update WBS progress"

# 5. PR → phase2-initial
git push -u origin pm/project-management
```

## 로컬 실행

```bash
cd project-management
npm install
npm run dev      # http://localhost:3000
npm run build    # 프로덕션 빌드
npm start        # 빌드 결과 실행
```

## 폴더 구조

```
project-management/
├── app/                # Next.js App Router 페이지·API
├── components/         # Header, Sidebar, Markdown, CRUD UI
├── content/
│   ├── ko/             # 한국어 마크다운 (페이지 본문)
│   └── en/             # 영어 마크다운
├── data/               # backlog.json, issues.json (CRUD)
├── lib/                # navigation, i18n, content loader
└── _legacy/            # 이전 HTML (참고용)
```

## 콘텐츠 수정 방법

| 수정 대상 | 파일 |
|-----------|------|
| Overview 문서 | `content/ko/overview/*.md`, `content/en/overview/*.md` |
| WBS 진행현황 | `content/ko/wbs.md`, `content/en/wbs.md` (또는 `scripts/generate_wbs.py`) |
| IA 페이지 상단 | `content/ko/ia.md`, `content/en/ia.md` |
| Issues 페이지 상단 | `content/ko/issues.md`, `content/en/issues.md` |
| IA 업무 데이터 | `/backlog` CRUD 또는 `data/backlog.json` |
| Issues 데이터 | `/issues` CRUD 또는 `data/issues.json` |
| 메뉴·UI 라벨 | `lib/i18n.ts`, `lib/navigation.ts` |

마크다운 파일에는 HTML 블록(`<!-- html -->`)을 포함할 수 있습니다. 복잡한 표(WBS 등)는 HTML로 작성합니다.

헤더 언어 드롭다운으로 **한국어 / English** 전환 시 해당 locale 폴더의 마크다운이 표시됩니다.

## 커밋 대상

- `app/`, `components/`, `content/`, `data/`, `lib/`, `scripts/`
- `package.json`, `tsconfig.json`, `next.config.ts`

## 주의

- PM 브랜치에서는 **`project-management/` 외 파일을 수정·커밋하지 않기**
