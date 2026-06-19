"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale } from "@/components/LocaleProvider";
import { formatMessage } from "@/lib/i18n";
import type { User } from "@/lib/types";

type FormState = {
  email: string;
  name: string;
  password: string;
};

const EMPTY: FormState = {
  email: "",
  name: "",
  password: "",
};

export default function UsersClient({ initialUsers }: { initialUsers: User[] }) {
  const { t } = useLocale();
  const [users, setUsers] = useState(initialUsers);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const res = await fetch("/api/users");
    setUsers(await res.json());
  }, []);

  useEffect(() => {
    setUsers(initialUsers);
  }, [initialUsers]);

  function startAdd() {
    setEditingId(null);
    setForm(EMPTY);
    setError("");
    setShowForm(true);
  }

  function startEdit(user: User) {
    setEditingId(user.id);
    setForm({ email: user.email, name: user.name, password: "" });
    setError("");
    setShowForm(true);
  }

  function resetForm() {
    setEditingId(null);
    setForm(EMPTY);
    setError("");
    setShowForm(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    const payload = editingId ? { ...form, id: editingId } : form;

    const res = await fetch("/api/users", {
      method: editingId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const data = (await res.json()) as { error?: string };
      setError(data.error === "Email already exists" ? t.settings.emailExists : t.settings.saveError);
      return;
    }

    await refresh();
    resetForm();
  }

  async function handleDelete(id: string) {
    if (!confirm(t.settings.confirmDelete)) return;
    await fetch("/api/users", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    await refresh();
    if (editingId === id) resetForm();
  }

  return (
    <div className="settings-page">
      <header className="page-header">
        <h1>{t.settings.userSettings}</h1>
        <p>{t.settings.userSettingsSubtitle}</p>
      </header>

      <section>
        <div className="toolbar">
          <span className="settings-count">
            {formatMessage(t.settings.total, { n: users.length })}
          </span>
          <button type="button" className="btn btn-primary" onClick={startAdd}>
            {t.settings.addUser}
          </button>
        </div>

        {showForm && (
          <form className="form-panel" onSubmit={handleSubmit}>
            <h2 className="form-panel-title">
              {editingId ? t.settings.editUser : t.settings.addUser}
            </h2>
            <div className="form-grid">
              <div className="form-field">
                <label htmlFor="user-email">{t.settings.email}</label>
                <input
                  id="user-email"
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  required
                  autoComplete="off"
                />
              </div>
              <div className="form-field">
                <label htmlFor="user-name">{t.settings.name}</label>
                <input
                  id="user-name"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  required
                />
              </div>
              <div className="form-field">
                <label htmlFor="user-password">{t.settings.password}</label>
                <input
                  id="user-password"
                  type="password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  required={!editingId}
                  placeholder={editingId ? t.settings.passwordKeep : undefined}
                  autoComplete="new-password"
                />
              </div>
            </div>
            {error && <p className="form-error">{error}</p>}
            <div className="btn-row form-panel-actions">
              <button type="submit" className="btn btn-primary">
                {editingId ? t.settings.update : t.settings.save}
              </button>
              <button type="button" className="btn" onClick={resetForm}>
                {t.settings.cancel}
              </button>
            </div>
          </form>
        )}

        <div className="table-scroll">
          <table className="users-table">
            <thead>
              <tr>
                <th>{t.settings.email}</th>
                <th>{t.settings.name}</th>
                <th className="col-actions">{t.settings.actions}</th>
              </tr>
            </thead>
            <tbody>
              {users.length === 0 ? (
                <tr>
                  <td colSpan={3} className="empty-cell">
                    {t.settings.empty}
                  </td>
                </tr>
              ) : (
                users.map((user) => (
                  <tr key={user.id}>
                    <td>{user.email}</td>
                    <td>{user.name}</td>
                    <td className="col-actions">
                      <div className="btn-row">
                        <button type="button" className="btn btn-sm" onClick={() => startEdit(user)}>
                          {t.settings.edit}
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-danger"
                          onClick={() => handleDelete(user.id)}
                        >
                          {t.settings.delete}
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
    </div>
  );
}
