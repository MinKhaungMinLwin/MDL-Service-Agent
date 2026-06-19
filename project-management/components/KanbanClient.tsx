"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale } from "@/components/LocaleProvider";
import { taskStatusLabel } from "@/lib/i18n";
import { formatScheduleRange } from "@/lib/wbs-schedule";
import { TASK_STATUSES, type WorkItem, statusBadgeClass } from "@/lib/types";

export default function KanbanClient({ initialItems }: { initialItems: WorkItem[] }) {
  const { locale, t } = useLocale();
  const [items, setItems] = useState(initialItems);

  const refresh = useCallback(async () => {
    const res = await fetch("/api/work");
    setItems(await res.json());
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const columns = TASK_STATUSES.map((status) => ({
    status,
    items: items.filter((item) => item.status === status),
  }));

  return (
    <div className="kanban-board">
      {columns.map(({ status, items: colItems }) => (
        <div key={status} className="kanban-column">
          <div className="kanban-column-header">
            <span className={`status-badge ${statusBadgeClass(status)}`}>
              {taskStatusLabel(locale, status)}
            </span>
            <span className="kanban-count">{colItems.length}</span>
          </div>
          <ul className="kanban-cards">
            {colItems.map((item) => (
              <li key={item.id} className="kanban-card">
                <div className="kanban-card-title">{item.title}</div>
                {item.assignee && (
                  <div className="kanban-card-meta">{t.work.assignee}: {item.assignee}</div>
                )}
                {(item.scheduleStart || item.scheduleEnd) && (
                  <div className="kanban-card-schedule">
                    {formatScheduleRange(item.scheduleStart, item.scheduleEnd, locale)}
                  </div>
                )}
                {item.description && (
                  <div className="kanban-card-deliver">{item.description}</div>
                )}
              </li>
            ))}
            {colItems.length === 0 && (
              <li className="kanban-empty">{t.kanban.empty}</li>
            )}
          </ul>
        </div>
      ))}
    </div>
  );
}
