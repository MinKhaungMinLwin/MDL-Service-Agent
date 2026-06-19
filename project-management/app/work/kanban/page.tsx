import AppShell from "@/components/AppShell";
import KanbanClient from "@/components/KanbanClient";
import { readWorkItems } from "@/lib/storage";

export default async function WorkKanbanPage() {
  const items = await readWorkItems();

  return (
    <AppShell section="work">
      <header className="page-header">
        <h1>Kanban</h1>
        <p>진행상태별 개발 작업 보드를 확인합니다.</p>
      </header>
      <KanbanClient initialItems={items} />
    </AppShell>
  );
}
