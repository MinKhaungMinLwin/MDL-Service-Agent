import AppShell from "@/components/AppShell";
import WbsClient from "@/components/WbsClient";
import { loadContentBoth } from "@/lib/content";
import { readBacklogItems, readJsonFile } from "@/lib/storage";
import type { WbsMeta, WbsTimeline } from "@/lib/wbs";

const DEFAULT_WBS_META: WbsMeta = {
  weekCount: 31,
  months: [
    { label: "4월", weeks: 5 },
    { label: "5월", weeks: 4 },
    { label: "6월", weeks: 4 },
    { label: "7월", weeks: 5 },
    { label: "8월", weeks: 4 },
    { label: "9월", weeks: 5 },
    { label: "10월", weeks: 4 },
  ],
  weekLabels: [],
  monthStartWeekIndices: [0, 5, 9, 13, 18, 22, 27],
};

export default async function WbsPage() {
  const [itemsKo, intro, meta, timeline] = await Promise.all([
    readBacklogItems("ko"),
    loadContentBoth("wbs-intro"),
    readJsonFile<WbsMeta>("wbs-meta.json", DEFAULT_WBS_META),
    readJsonFile<WbsTimeline>("wbs-timeline.json", {}),
  ]);

  const resolvedMeta =
    meta.months.length > 0 ? meta : DEFAULT_WBS_META;

  return (
    <AppShell section="wbs" wide>
      <WbsClient initialItems={itemsKo} meta={resolvedMeta} timeline={timeline} intro={intro} />
    </AppShell>
  );
}
