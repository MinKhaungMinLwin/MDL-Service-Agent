import { notFound } from "next/navigation";
import TaskDetailInfo from "@/components/TaskDetailInfo";
import { readBacklogItems } from "@/lib/storage";

type Props = {
  params: Promise<{ id: string }>;
};

export default async function TaskInfoPage({ params }: Props) {
  const { id } = await params;
  const items = await readBacklogItems("ko");
  const item = items.find((entry) => entry.id === id);
  if (!item) notFound();

  return <TaskDetailInfo item={item} allItems={items} />;
}
