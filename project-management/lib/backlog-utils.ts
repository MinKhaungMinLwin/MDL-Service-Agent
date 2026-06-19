import type { BacklogItem } from "@/lib/types";

export function normalizeBacklogItem(item: Partial<BacklogItem> & { id: string }): BacklogItem {
  return {
    id: item.id,
    l1: item.l1 ?? "",
    l2: item.l2 ?? "",
    task: item.task ?? "",
    status: item.status ?? "진행예정",
    deliverable: item.deliverable ?? "",
    scheduleStart: item.scheduleStart ?? "",
    scheduleEnd: item.scheduleEnd ?? "",
  };
}

/** Keep IA tree/table grouping stable regardless of JSON array order. */
export function sortBacklogItems(items: BacklogItem[]): BacklogItem[] {
  const l1Order: string[] = [];
  const l2Order = new Map<string, string[]>();

  for (const item of items) {
    if (!l1Order.includes(item.l1)) l1Order.push(item.l1);
    const l2s = l2Order.get(item.l1) ?? [];
    if (!l2s.includes(item.l2)) l2s.push(item.l2);
    l2Order.set(item.l1, l2s);
  }

  return [...items].sort((a, b) => {
    const byL1 = l1Order.indexOf(a.l1) - l1Order.indexOf(b.l1);
    if (byL1 !== 0) return byL1;
    const l2s = l2Order.get(a.l1) ?? [];
    const byL2 = l2s.indexOf(a.l2) - l2s.indexOf(b.l2);
    if (byL2 !== 0) return byL2;
    return a.id.localeCompare(b.id);
  });
}
