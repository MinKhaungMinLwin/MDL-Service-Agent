import type { BacklogItem } from "@/lib/types";
import { sortBacklogItems } from "@/lib/backlog-utils";

export type WbsMeta = {
  weekCount: number;
  months: { label: string; weeks: number }[];
  weekLabels: string[];
  monthStartWeekIndices: number[];
};

export type WbsTimeline = Record<string, string[]>;

export type WbsRow = {
  item: BacklogItem;
  showL1: boolean;
  l1RowSpan: number;
  l1Merged: boolean;
  showL2: boolean;
  l2RowSpan: number;
};

export function calcProgress(items: BacklogItem[]): number {
  if (items.length === 0) return 0;
  const done = items.filter((i) => i.status === "완료").length;
  return Math.round((done / items.length) * 100);
}

export function buildWbsRows(items: BacklogItem[]): WbsRow[] {
  const sorted = sortBacklogItems(items);
  const rows: WbsRow[] = [];
  let i = 0;
  while (i < sorted.length) {
    const l1 = sorted[i].l1;
    let l1End = i;
    while (l1End < sorted.length && sorted[l1End].l1 === l1) l1End++;
    const l1Count = l1End - i;

    let j = i;
    while (j < l1End) {
      const l2 = sorted[j].l2;
      let l2End = j;
      while (l2End < l1End && sorted[l2End].l2 === l2) l2End++;
      const l2Count = l2End - j;
      const merged = l1 === l2;

      for (let k = j; k < l2End; k++) {
        rows.push({
          item: sorted[k],
          showL1: k === i,
          l1RowSpan: l1Count,
          l1Merged: merged,
          showL2: !merged && k === j,
          l2RowSpan: l2Count,
        });
      }
      j = l2End;
    }
    i = l1End;
  }
  return rows;
}
