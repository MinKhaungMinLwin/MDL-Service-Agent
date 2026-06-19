"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale } from "@/components/LocaleProvider";
import { formatMessage } from "@/lib/i18n";
import { AGENT_STATUSES, type Agent, type AgentStatus, statusBadgeClass } from "@/lib/types";

const EMPTY: Omit<Agent, "id" | "createdAt" | "updatedAt"> = {
  name: "",
  description: "",
  status: "개발중",
  logic: "",
};

function agentStatusLabel(status: AgentStatus, t: ReturnType<typeof useLocale>["t"]) {
  const map = {
    개발중: t.agents.statusDev,
    테스트중: t.agents.statusTest,
    배포완료: t.agents.statusDone,
  };
  return map[status];
}

export default function AgentsClient({ initialAgents }: { initialAgents: Agent[] }) {
  const router = useRouter();
  const { t } = useLocale();
  const [agents, setAgents] = useState(initialAgents);
  const [form, setForm] = useState(EMPTY);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const res = await fetch("/api/agents");
    setAgents(await res.json());
  }, []);

  useEffect(() => {
    setAgents(initialAgents);
  }, [initialAgents]);

  function resetForm() {
    setForm(EMPTY);
    setError("");
    setShowForm(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    const res = await fetch("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });

    if (!res.ok) {
      setError(t.agents.saveError);
      return;
    }

    const created = (await res.json()) as Agent;
    await refresh();
    resetForm();
    router.push(`/agents/${created.id}/logic`);
  }

  async function handleDelete(id: string) {
    if (!confirm(t.agents.confirmDelete)) return;
    await fetch("/api/agents", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    await refresh();
  }

  return (
    <>
      <div className="toolbar">
        <span className="settings-count">
          {formatMessage(t.agents.total, { n: agents.length })}
        </span>
        <button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}>
          {t.agents.addAgent}
        </button>
      </div>

      {showForm && (
        <form className="form-panel" onSubmit={handleSubmit}>
          <h2 className="form-panel-title">{t.agents.addAgent}</h2>
          <div className="form-grid">
            <div className="form-field">
              <label htmlFor="agent-name">{t.agents.name}</label>
              <input
                id="agent-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </div>
            <div className="form-field">
              <label htmlFor="agent-status">{t.agents.status}</label>
              <select
                id="agent-status"
                value={form.status}
                onChange={(e) => setForm({ ...form, status: e.target.value as AgentStatus })}
              >
                {AGENT_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {agentStatusLabel(status, t)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-field" style={{ marginTop: "0.75rem" }}>
            <label htmlFor="agent-desc">{t.agents.description}</label>
            <input
              id="agent-desc"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>
          {error && <p className="form-error">{error}</p>}
          <div className="btn-row form-panel-actions">
            <button type="submit" className="btn btn-primary">
              {t.agents.save}
            </button>
            <button type="button" className="btn" onClick={resetForm}>
              {t.agents.cancel}
            </button>
          </div>
        </form>
      )}

      <div className="agent-card-grid">
        {agents.length === 0 ? (
          <p className="agent-empty">{t.agents.empty}</p>
        ) : (
          agents.map((agent) => (
            <article key={agent.id} className="agent-card">
              <div className="agent-card-header">
                <span className={`status-badge ${statusBadgeClass(agent.status)}`}>
                  {agentStatusLabel(agent.status, t)}
                </span>
                <span className="agent-card-date">{agent.updatedAt}</span>
              </div>
              <h3 className="agent-card-title">{agent.name}</h3>
              {agent.description && <p className="agent-card-desc">{agent.description}</p>}
              <div className="btn-row agent-card-actions">
                <Link href={`/agents/${agent.id}/logic`} className="btn btn-sm btn-primary">
                  {t.agents.open}
                </Link>
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  onClick={() => handleDelete(agent.id)}
                >
                  {t.agents.delete}
                </button>
              </div>
            </article>
          ))
        )}
      </div>
    </>
  );
}
