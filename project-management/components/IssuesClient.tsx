"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale } from "@/components/LocaleProvider";
import { formatMessage } from "@/lib/i18n";
import {
  type Issue,
  type IssuePriority,
  type IssueStatus,
  ISSUE_PRIORITIES,
  ISSUE_STATUSES,
  statusBadgeClass,
} from "@/lib/types";

const EMPTY: Omit<Issue, "id" | "createdAt"> = {
  title: "",
  status: "Open",
  priority: "Medium",
  assignee: "",
  description: "",
};

function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge ${statusBadgeClass(status)}`}>{status}</span>;
}

export default function IssuesClient({ initialItems }: { initialItems: Issue[] }) {
  const { t } = useLocale();
  const [items, setItems] = useState(initialItems);
  const [form, setForm] = useState(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const refresh = useCallback(async () => {
    const res = await fetch("/api/issues");
    setItems(await res.json());
  }, []);

  useEffect(() => {
    setItems(initialItems);
  }, [initialItems]);

  function startEdit(item: Issue) {
    setEditingId(item.id);
    setForm({
      title: item.title,
      status: item.status,
      priority: item.priority,
      assignee: "",
      description: item.description,
    });
    setShowForm(true);
  }

  function resetForm() {
    setEditingId(null);
    setForm(EMPTY);
    setShowForm(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (editingId) {
      const existing = items.find((i) => i.id === editingId)!;
      await fetch("/api/issues", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, id: editingId, createdAt: existing.createdAt }),
      });
    } else {
      await fetch("/api/issues", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
    }
    await refresh();
    resetForm();
  }

  async function handleDelete(id: string) {
    if (!confirm(t.issues.confirmDelete)) return;
    await fetch("/api/issues", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    await refresh();
    if (editingId === id) resetForm();
  }

  return (
    <>
      <section>
        <div className="toolbar">
          <span style={{ color: "var(--muted)", fontSize: "0.875rem" }}>
            {formatMessage(t.issues.total, { n: items.length })}
          </span>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              resetForm();
              setShowForm(true);
            }}
          >
            {t.issues.addIssue}
          </button>
        </div>

        {showForm && (
          <form className="form-panel" onSubmit={handleSubmit}>
            <div className="form-grid">
              <div className="form-field" style={{ gridColumn: "1 / -1" }}>
                <label>{t.issues.titleLabel}</label>
                <input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  required
                />
              </div>
              <div className="form-field">
                <label>{t.issues.status}</label>
                <select
                  value={form.status}
                  onChange={(e) => setForm({ ...form, status: e.target.value as IssueStatus })}
                >
                  {ISSUE_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-field">
                <label>{t.issues.priority}</label>
                <select
                  value={form.priority}
                  onChange={(e) =>
                    setForm({ ...form, priority: e.target.value as IssuePriority })
                  }
                >
                  {ISSUE_PRIORITIES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="form-field" style={{ marginBottom: "0.75rem" }}>
              <label>{t.issues.description}</label>
              <textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
            <div className="btn-row">
              <button type="submit" className="btn btn-primary">
                {editingId ? t.issues.update : t.issues.save}
              </button>
              <button type="button" className="btn" onClick={resetForm}>
                {t.issues.cancel}
              </button>
            </div>
          </form>
        )}

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t.issues.colId}</th>
                <th>{t.issues.colTitle}</th>
                <th>{t.issues.colStatus}</th>
                <th>{t.issues.colPriority}</th>
                <th>{t.issues.colCreated}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td>—</td>
                  <td colSpan={5} style={{ color: "var(--muted)", textAlign: "center" }}>
                    {t.issues.empty}
                  </td>
                </tr>
              ) : (
                items.map((item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td>
                    <td>{item.title}</td>
                    <td>
                      <StatusBadge status={item.status} />
                    </td>
                    <td>{item.priority}</td>
                    <td>{item.createdAt}</td>
                    <td>
                      <div className="btn-row">
                        <button type="button" className="btn btn-sm" onClick={() => startEdit(item)}>
                          {t.issues.edit}
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-danger"
                          onClick={() => handleDelete(item.id)}
                        >
                          {t.issues.delete}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
