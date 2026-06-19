"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useLocale } from "@/components/LocaleProvider";
import ContentPage from "@/components/ContentPage";
import { taskStatusLabel } from "@/lib/i18n";
import type { Locale } from "@/lib/i18n";
import type { BacklogItem } from "@/lib/types";
import { statusBadgeClass } from "@/lib/types";
import { buildWbsRows, calcProgress, type WbsMeta, type WbsTimeline } from "@/lib/wbs";
import { scheduleToTimeline } from "@/lib/wbs-schedule";

type Props = {
  initialItems: BacklogItem[];
  meta: WbsMeta;
  timeline: WbsTimeline;
  intro?: Partial<Record<Locale, string>>;
};

function monthSpans(meta: WbsMeta) {
  let weekIndex = 0;
  return meta.months.map((month, i) => {
    const start = weekIndex;
    weekIndex += month.weeks;
    return { ...month, startIndex: start, isFirst: i === 0 };
  });
}

export default function WbsClient({ initialItems, meta, timeline, intro }: Props) {
  const { locale, t } = useLocale();
  const [items, setItems] = useState(initialItems);

  const refresh = useCallback(async () => {
    const res = await fetch(`/api/backlog?locale=${locale}`);
    setItems(await res.json());
  }, [locale]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const progress = calcProgress(items);
  const rows = buildWbsRows(items);
  const months = monthSpans(meta);
  const weekLabels = t.wbs.weekLabels;
  const monthStartSet = new Set(meta.monthStartWeekIndices);

  return (
    <>
      <ContentPage contentPath="wbs-intro" initial={intro} />

      <div className="meta-row" style={{ marginTop: "1rem" }}>
        <span className="meta-pill">
          <strong>{t.wbs.overallProgress}</strong> {progress}%
        </span>
      </div>
      <div className="progress-bar progress-bar-lg" style={{ marginTop: "1rem" }}>
        <div className="progress-fill" style={{ width: `${progress}%` }} />
      </div>

      <section>
        <h2>{t.wbs.scheduleTitle}</h2>
        <div className="table-scroll">
          <table className="wbs-table">
            <thead>
              <tr>
                <th rowSpan={2} colSpan={2} className="col-b">
                  {t.wbs.colCategory}
                </th>
                <th rowSpan={2} className="col-task">
                  {t.wbs.colTask}
                </th>
                <th rowSpan={2} className="status-col">
                  {t.wbs.colStatus}
                </th>
                {months.map((month, i) => (
                  <th
                    key={month.label}
                    colSpan={month.weeks}
                    className={`month-header ${i === 0 ? "timeline-start" : "month-start"}`}
                  >
                    {t.wbs.months[i] ?? month.label}
                  </th>
                ))}
              </tr>
              <tr>
                {weekLabels.map((label, i) => (
                  <th
                    key={`${i}-${label}`}
                    className={`week-col${monthStartSet.has(i) ? " month-start" : ""}`}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const tl =
                  row.item.scheduleStart && row.item.scheduleEnd
                    ? scheduleToTimeline(
                        row.item.scheduleStart,
                        row.item.scheduleEnd,
                        row.item.status,
                      )
                    : (timeline[row.item.id] ?? Array(meta.weekCount).fill(""));
                return (
                  <tr key={row.item.id} id={row.item.id} data-task-id={row.item.id}>
                    {row.showL1 &&
                      (row.l1Merged ? (
                        <td
                          rowSpan={row.l1RowSpan}
                          colSpan={2}
                          className="l1-cell l1-merged"
                        >
                          {row.item.l1}
                        </td>
                      ) : (
                        <td rowSpan={row.l1RowSpan} className="l1-cell">
                          {row.item.l1}
                        </td>
                      ))}
                    {row.showL2 && (
                      <td rowSpan={row.l2RowSpan} className="l2-cell">
                        {row.item.l2}
                      </td>
                    )}
                    <td className="task-cell">
                      <Link href={`/task/${row.item.id}/info`} className="wbs-task-link">
                        {row.item.task}
                      </Link>
                    </td>
                    <td className="status-col">
                      <span className={`status-badge ${statusBadgeClass(row.item.status)}`}>
                        {taskStatusLabel(locale, row.item.status)}
                      </span>
                    </td>
                    {tl.map((cell, i) => {
                      const classes = ["tl-cell"];
                      if (cell) classes.push(cell);
                      if (monthStartSet.has(i)) classes.push("month-start");
                      return <td key={i} className={classes.join(" ")} />;
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
