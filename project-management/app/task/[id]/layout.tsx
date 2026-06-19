import { notFound } from "next/navigation";
import AppShell from "@/components/AppShell";
import TaskDetailTabs from "@/components/TaskDetailTabs";
import { readBacklogItems } from "@/lib/storage";

type Props = {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
};

export default async function TaskDetailLayout({ children, params }: Props) {
  const { id } = await params;
  const items = await readBacklogItems("ko");
  const item = items.find((entry) => entry.id === id);
  if (!item) notFound();

  return (
    <AppShell section="backlog">
      <div className="detail-header">
        <h1 className="detail-title">{item.task}</h1>
        <p className="detail-meta">
          {item.l1} › {item.l2}
        </p>
      </div>
      <TaskDetailTabs taskId={id} />
      {children}
    </AppShell>
  );
}
