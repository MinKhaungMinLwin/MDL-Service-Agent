"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import AssigneeSelect from "@/components/AssigneeSelect";
import { useLocale } from "@/components/LocaleProvider";
import { formatMessage, taskStatusLabel } from "@/lib/i18n";
import {
  TASK_STATUSES,
  type TaskStatus,
  type User,
  type WorkItem,
  statusBadgeClass,
} from "@/lib/types";

const EMPTY: Omit<WorkItem, "id"> = {
  title: "",
  status: "진행예정",
  assignee: "",
  description: "",
  scheduleStart: "",
  scheduleEnd: "",
};

function StatusBadge({ status }: { status: TaskStatus }) {
  const { locale } = useLocale();
  return (
    <span className={`status-badge ${statusBadgeClass(status)}`}>
      {taskStatusLabel(locale, status)}
    </span>
  );
}

function ScheduleRangeDisplay({ start, end }: { start: string; end: string }) {
  if (!start && !end) return null;
  const same = start && end && start === end;
  return (
    <span className="schedule-range">
      {start && <span className="schedule-start">{start}</span>}
      {end && !same && <span className="schedule-end">{end}</span>}
    </span>
  );
}

export default function WorkBacklogClient({
  initialItems,
  initialUsers,
}: {
  initialItems: WorkItem[];
  initialUsers: User[];
}) {
  const { locale, t } = useLocale();
  const [items, setItems] = useState(initialItems);
  const [users, setUsers] = useState(initialUsers);
  const [form, setForm] = useState(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [showViewModal, setShowViewModal] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const refresh = useCallback(async () => {
    const [workRes, usersRes] = await Promise.all([
      fetch("/api/work"),
      fetch("/api/users"),
    ]);
    setItems(await workRes.json());
    setUsers(await usersRes.json());
  }, []);

  useEffect(() => {
    setUsers(initialUsers);
  }, [initialUsers]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function openView(item: WorkItem) {
    setEditingId(item.id);
    setForm({
      title: item.title,
      status: item.status,
      assignee: item.assignee,
      description: item.description,
      scheduleStart: item.scheduleStart,
      scheduleEnd: item.scheduleEnd,
    });
    setShowViewModal(true);
  }

  function closeViewModal() {
    setShowViewModal(false);
    setEditingId(null);
    setForm(EMPTY);
  }

  function resetAddForm() {
    setEditingId(null);
    setForm(EMPTY);
    setShowAddForm(false);
  }

  async function handleAddSubmit(e: React.FormEvent) {
    e.preventDefault();
    await fetch("/api/work", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    await refresh();
    resetAddForm();
  }

  async function handleViewSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!editingId) return;
    await fetch("/api/work", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, id: editingId }),
    });
    await refresh();
    closeViewModal();
  }

  async function handleDelete(id: string) {
    if (!confirm(t.work.confirmDelete)) return;
    await fetch("/api/work", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    await refresh();
    closeViewModal();
    resetAddForm();
  }

  return (
    <>
      <section>
        <div className="toolbar">
          <span style={{ color: "var(--muted)", fontSize: "0.875rem" }}>
            {formatMessage(t.work.total, { n: items.length })}
          </span>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              resetAddForm();
              setShowAddForm(true);
            }}
          >
            {t.work.addItem}
          </button>
        </div>

        {showAddForm && (
          <form className="form-panel" onSubmit={handleAddSubmit}>
            <div className="form-field" style={{ marginBottom: "0.75rem" }}>
              <label>{t.work.titleLabel}</label>
              <input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                required
              />
            </div>
            <div className="form-grid">
              <div className="form-field">
                <label>{t.work.assignee}</label>
                <AssigneeSelect
                  users={users}
                  value={form.assignee}
                  onChange={(assignee) => setForm({ ...form, assignee })}
                  selectLabel={t.work.selectAssignee}
                  noUsersHint={t.work.noUsers}
                />
              </div>
              <div className="form-field">
                <label>{t.work.status}</label>
                <select
                  value={form.status}
                  onChange={(e) => setForm({ ...form, status: e.target.value as TaskStatus })}
                >
                  {TASK_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {taskStatusLabel(locale, s)}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="form-grid" style={{ marginTop: "0.75rem" }}>
              <div className="form-field">
                <label>{t.work.scheduleStart}</label>
                <input
                  type="date"
                  value={form.scheduleStart}
                  onChange={(e) => setForm({ ...form, scheduleStart: e.target.value })}
                />
              </div>
              <div className="form-field">
                <label>{t.work.scheduleEnd}</label>
                <input
                  type="date"
                  value={form.scheduleEnd}
                  min={form.scheduleStart || undefined}
                  onChange={(e) => setForm({ ...form, scheduleEnd: e.target.value })}
                />
              </div>
            </div>
            <div className="form-field" style={{ marginTop: "0.75rem" }}>
              <label>{t.work.description}</label>
              <input
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
            <div className="btn-row" style={{ marginTop: "0.75rem" }}>
              <button type="submit" className="btn btn-primary">
                {t.work.save}
              </button>
              <button type="button" className="btn" onClick={resetAddForm}>
                {t.work.cancel}
              </button>
            </div>
          </form>
        )}

        <div className="table-scroll">
          <table className="task-table">
            <thead>
              <tr>
                <th>{t.work.colTitle}</th>
                <th>{t.work.colAssignee}</th>
                <th>{t.work.colStatus}</th>
                <th>{t.work.colSchedule}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: "center", color: "var(--muted)" }}>
                    {t.work.empty}
                  </td>
                </tr>
              ) : (
                items.map((item) => (
                  <tr key={item.id}>
                    <td>{item.title}</td>
                    <td>{item.assignee}</td>
                    <td>
                      <StatusBadge status={item.status} />
                    </td>
                    <td>
                      <ScheduleRangeDisplay
                        start={item.scheduleStart}
                        end={item.scheduleEnd}
                      />
                    </td>
                    <td>
                      <button type="button" className="btn btn-sm" onClick={() => openView(item)}>
                        {t.work.view}
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {mounted &&
        showViewModal &&
        editingId &&
        createPortal(
          <div
            className="modal-overlay"
            onClick={(e) => {
              if (e.target === e.currentTarget) closeViewModal();
            }}
          >
            <div className="modal-panel" role="dialog" aria-modal="true">
              <div className="modal-header">
                <h3>{t.work.viewItem}</h3>
                <button type="button" className="modal-close" onClick={closeViewModal}>
                  ×
                </button>
              </div>
              <form onSubmit={handleViewSubmit}>
                <div className="modal-body">
                  <div className="form-field" style={{ marginBottom: "0.75rem" }}>
                    <label>{t.work.titleLabel}</label>
                    <input
                      value={form.title}
                      onChange={(e) => setForm({ ...form, title: e.target.value })}
                      required
                    />
                  </div>
                  <div className="form-grid">
                    <div className="form-field">
                      <label>{t.work.assignee}</label>
                      <AssigneeSelect
                        users={users}
                        value={form.assignee}
                        onChange={(assignee) => setForm({ ...form, assignee })}
                        selectLabel={t.work.selectAssignee}
                        noUsersHint={t.work.noUsers}
                      />
                    </div>
                    <div className="form-field">
                      <label>{t.work.status}</label>
                      <select
                        value={form.status}
                        onChange={(e) =>
                          setForm({ ...form, status: e.target.value as TaskStatus })
                        }
                      >
                        {TASK_STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {taskStatusLabel(locale, s)}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="form-grid" style={{ marginTop: "0.75rem" }}>
                    <div className="form-field">
                      <label>{t.work.scheduleStart}</label>
                      <input
                        type="date"
                        value={form.scheduleStart}
                        onChange={(e) => setForm({ ...form, scheduleStart: e.target.value })}
                      />
                    </div>
                    <div className="form-field">
                      <label>{t.work.scheduleEnd}</label>
                      <input
                        type="date"
                        value={form.scheduleEnd}
                        min={form.scheduleStart || undefined}
                        onChange={(e) => setForm({ ...form, scheduleEnd: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="form-field" style={{ marginTop: "0.75rem" }}>
                    <label>{t.work.description}</label>
                    <input
                      value={form.description}
                      onChange={(e) => setForm({ ...form, description: e.target.value })}
                    />
                  </div>
                </div>
                <div className="modal-footer">
                  <button
                    type="button"
                    className="btn btn-danger"
                    onClick={() => handleDelete(editingId)}
                  >
                    {t.work.delete}
                  </button>
                  <div className="btn-row">
                    <button type="button" className="btn" onClick={closeViewModal}>
                      {t.work.cancel}
                    </button>
                    <button type="submit" className="btn btn-primary">
                      {t.work.update}
                    </button>
                  </div>
                </div>
              </form>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
