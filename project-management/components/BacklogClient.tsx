"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useLocale } from "@/components/LocaleProvider";
import TaskFormFields from "@/components/TaskFormFields";
import { taskStatusLabel } from "@/lib/i18n";
import {
  type BacklogItem,
  type TaskStatus,
  statusBadgeClass,
} from "@/lib/types";
import { sortBacklogItems } from "@/lib/backlog-utils";
import { formatScheduleRange } from "@/lib/wbs-schedule";

const EMPTY: Omit<BacklogItem, "id"> = {
  l1: "",
  l2: "",
  task: "",
  status: "진행예정",
  deliverable: "",
  scheduleStart: "",
  scheduleEnd: "",
};

function getL2Options(items: BacklogItem[], l1: string, includeL2?: string) {
  const set = new Set(
    items.filter((item) => item.l1 === l1).map((item) => item.l2).filter(Boolean),
  );
  if (includeL2) set.add(includeL2);
  return [...set].sort();
}

function buildTree(items: BacklogItem[]) {
  const l1Map = new Map<string, Map<string, BacklogItem[]>>();
  for (const item of items) {
    if (!l1Map.has(item.l1)) l1Map.set(item.l1, new Map());
    const l2Map = l1Map.get(item.l1)!;
    if (!l2Map.has(item.l2)) l2Map.set(item.l2, []);
    l2Map.get(item.l2)!.push(item);
  }
  return l1Map;
}

function StatusBadge({ status }: { status: TaskStatus }) {
  const { locale } = useLocale();
  return (
    <span className={`status-badge ${statusBadgeClass(status)}`}>
      {taskStatusLabel(locale, status)}
    </span>
  );
}

function ScheduleRangeDisplay({
  start,
  end,
  className,
  stacked = true,
  locale = "ko",
}: {
  start: string;
  end: string;
  className?: string;
  stacked?: boolean;
  locale?: "ko" | "en";
}) {
  if (!start && !end) return null;
  if (!stacked) {
    return (
      <span className={className}>
        {formatScheduleRange(start, end, locale)}
      </span>
    );
  }
  const same = start && end && start === end;
  return (
    <span className={["schedule-range", className].filter(Boolean).join(" ")}>
      {start && <span className="schedule-start">{start}</span>}
      {end && !same && <span className="schedule-end">{end}</span>}
    </span>
  );
}

export default function BacklogClient({ initialItems }: { initialItems: BacklogItem[] }) {
  const { locale, t } = useLocale();
  const [items, setItems] = useState(initialItems);
  const [form, setForm] = useState<Omit<BacklogItem, "id">>(EMPTY);
  const [showAddForm, setShowAddForm] = useState(false);

  const refresh = useCallback(async () => {
    const res = await fetch(`/api/backlog?locale=${locale}`);
    setItems(await res.json());
  }, [locale]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function resetAddForm() {
    setForm(EMPTY);
    setShowAddForm(false);
  }

  async function handleAddSubmit(e: React.FormEvent) {
    e.preventDefault();
    await fetch("/api/backlog", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    await refresh();
    resetAddForm();
  }

  const labels = {
    l1: t.backlog.l1,
    selectL1: t.backlog.selectL1,
    l2: t.backlog.l2,
    selectL2: t.backlog.selectL2,
    status: t.backlog.status,
    scheduleStart: t.backlog.scheduleStart,
    scheduleEnd: t.backlog.scheduleEnd,
    task: t.backlog.task,
    deliverable: t.backlog.deliverable,
  };

  const tree = buildTree(sortBacklogItems(items));

  return (
    <>
      <section>
        <div className="toolbar">
          <h2 style={{ margin: 0 }}>{t.backlog.treeTitle}</h2>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              resetAddForm();
              const defaultL1 = [
                ...new Set(items.map((item) => item.l1).filter(Boolean)),
              ].sort()[0];
              if (defaultL1) {
                const defaultL2 = getL2Options(items, defaultL1)[0] ?? "";
                setForm({ ...EMPTY, l1: defaultL1, l2: defaultL2 });
              }
              setShowAddForm(true);
            }}
          >
            {t.backlog.addItem}
          </button>
        </div>

        {showAddForm && (
          <form className="form-panel" onSubmit={handleAddSubmit}>
            <TaskFormFields
              form={form}
              setForm={setForm}
              items={items}
              locale={locale}
              labels={labels}
            />
            <div className="btn-row" style={{ marginTop: "0.75rem" }}>
              <button type="submit" className="btn btn-primary">
                {t.backlog.save}
              </button>
              <button type="button" className="btn" onClick={resetAddForm}>
                {t.backlog.cancel}
              </button>
            </div>
          </form>
        )}

        <div className="ia-tree">
          {[...tree.entries()].map(([l1, l2Map]) => (
            <div key={l1} className="ia-l1">
              <div className="ia-l1-title">{l1}</div>
              {[...l2Map.entries()].map(([l2, tasks]) => (
                <div key={l2} className="ia-l2">
                  <div className="ia-l2-title">{l2}</div>
                  <ul className="ia-l3-list">
                    {tasks.map((item) => (
                      <li key={item.id} className="ia-l3-item">
                        <span className="ia-task">{item.task}</span>
                        <StatusBadge status={item.status} />
                        {(item.scheduleStart || item.scheduleEnd) && (
                          <ScheduleRangeDisplay
                            className="ia-schedule"
                            stacked={false}
                            locale={locale}
                            start={item.scheduleStart ?? ""}
                            end={item.scheduleEnd ?? ""}
                          />
                        )}
                        {item.deliverable && (
                          <span className="ia-deliver">{item.deliverable}</span>
                        )}
                        <span className="ia-actions">
                          <Link href={`/task/${item.id}/info`} className="btn btn-sm">
                            {t.backlog.view}
                          </Link>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>{t.backlog.allTasks}</h2>
        <div className="table-scroll">
          <table className="task-table">
            <thead>
              <tr>
                <th>{t.backlog.colL1}</th>
                <th>{t.backlog.colL2}</th>
                <th>{t.backlog.task}</th>
                <th>{t.backlog.status}</th>
                <th>{t.backlog.colSchedule}</th>
                <th>{t.backlog.deliverable}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sortBacklogItems(items).map((item) => (
                <tr key={item.id}>
                  <td>{item.l1}</td>
                  <td>{item.l2}</td>
                  <td>{item.task}</td>
                  <td>
                    <StatusBadge status={item.status} />
                  </td>
                  <td>
                    <ScheduleRangeDisplay
                      start={item.scheduleStart ?? ""}
                      end={item.scheduleEnd ?? ""}
                    />
                  </td>
                  <td>{item.deliverable}</td>
                  <td>
                    <Link href={`/task/${item.id}/info`} className="btn btn-sm">
                      {t.backlog.view}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
