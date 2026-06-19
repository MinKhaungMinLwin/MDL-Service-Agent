import type { WorkItem } from "@/lib/types";

export function normalizeWorkItem(item: Partial<WorkItem> & { id: string }): WorkItem {
  return {
    id: item.id,
    title: item.title ?? "",
    status: item.status ?? "진행예정",
    assignee: item.assignee ?? "",
    description: item.description ?? "",
    scheduleStart: item.scheduleStart ?? "",
    scheduleEnd: item.scheduleEnd ?? "",
  };
}
