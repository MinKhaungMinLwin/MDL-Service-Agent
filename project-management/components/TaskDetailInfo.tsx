"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useLocale } from "@/components/LocaleProvider";
import TaskFormFields from "@/components/TaskFormFields";
import type { BacklogItem } from "@/lib/types";

type Props = {
  item: BacklogItem;
  allItems: BacklogItem[];
};

export default function TaskDetailInfo({ item, allItems }: Props) {
  const router = useRouter();
  const { locale, t } = useLocale();
  const [form, setForm] = useState<Omit<BacklogItem, "id">>({
    l1: item.l1,
    l2: item.l2,
    task: item.task,
    status: item.status,
    deliverable: item.deliverable,
    scheduleStart: item.scheduleStart ?? "",
    scheduleEnd: item.scheduleEnd ?? "",
  });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await fetch("/api/backlog", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, id: item.id }),
    });
    router.refresh();
  }

  async function handleDelete() {
    if (!confirm(t.backlog.confirmDelete)) return;
    await fetch("/api/backlog", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: item.id }),
    });
    router.push("/task");
    router.refresh();
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

  return (
    <form className="form-panel" onSubmit={handleSubmit}>
      <TaskFormFields
        form={form}
        setForm={setForm}
        items={allItems}
        locale={locale}
        labels={labels}
      />
      <div className="btn-row" style={{ marginTop: "0.75rem" }}>
        <button type="button" className="btn btn-danger" onClick={handleDelete}>
          {t.backlog.delete}
        </button>
        <div className="btn-row" style={{ marginLeft: "auto" }}>
          <Link href="/task" className="btn">
            {t.backlog.backToList}
          </Link>
          <button type="submit" className="btn btn-primary">
            {t.backlog.update}
          </button>
        </div>
      </div>
    </form>
  );
}
