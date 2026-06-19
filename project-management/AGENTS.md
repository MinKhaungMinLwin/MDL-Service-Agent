# project-management — Agent Guide

이 문서는 **`project-management/`** 디렉터리만 대상으로 한다. 다른 하위 프로젝트는 범위에 포함하지 않는다.

## 스택

- Next.js 15 App Router, React 19
- 데이터: `data/*.json` + `/app/api/*` CRUD
- 콘텐츠: `content/{ko,en}/*.md`

## 주요 경로

| 메뉴 | 경로 | 데이터 |
|------|------|--------|
| Task IA | `/task`, `/task/[id]/info` | `data/backlog.json` |
| WBS | `/wbs` | backlog + `data/wbs-*.json` |
| Work | `/work/backlog`, `/work/kanban` | `data/work.json` |
| Issues | `/issues` | `data/issues.json` |
| Agent | `/agents`, `/agents/[id]/logic`, `/agents/[id]/playground` | `data/agents.json` |
| 사용자 설정 | `/settings/users` | `data/users.json` |

## 코드 수정 후 — 페이지 로딩 검증 (필수)

dev 서버 실행 중 `npm run build` 또는 dev 서버 중복 실행 시 `.next` 캐시가 깨져 500 오류가 자주 발생한다. **기능 수정 완료 후 반드시 페이지 로딩까지 확인한다.**

### 1. 캐시 오류 패턴

아래 메시지면 코드 버그보다 **캐시 문제**를 우선 의심한다.

- `Cannot find module './숫자.js'`
- `ENOENT: ... .next/server/...`
- `Cannot find module './vendor-chunks/...'`
- 여러 페이지가 동시에 500

### 2. 캐시 복구

```bash
lsof -ti:3000,3002 | xargs kill -9 2>/dev/null
cd project-management && rm -rf .next && npm run dev
```

또는 `npm run dev:clean`

### 3. HTTP 상태 확인

dev 서버(`http://localhost:3000`) 기준 주요 경로가 **200**인지 확인한다.

- `/overview`
- `/task`
- `/wbs`
- `/issues`
   - `/work/backlog`
   - `/agents`
   - `/settings/users`

### 4. 주의

- `npm run dev` 실행 중에는 `npm run build` 하지 않는다.
- dev 서버는 **한 포트, 한 프로세스**만 유지한다.
- build 검증이 필요하면 dev 종료 후 build → `.next` 삭제 → dev 재시작.

### 5. 보고

- 캐시 문제였으면 원인과 복구 방법을 사용자에게 간단히 알린다.
- 200이 아닌 경로와 오류 메시지를 함께 전달한다.

## 작업 원칙

- 변경 범위는 요청된 기능에만 한정한다.
- 기존 컴포넌트·API·i18n(`lib/i18n.ts`) 패턴을 따른다.
- 커밋·PR은 사용자가 요청할 때만 수행한다.
