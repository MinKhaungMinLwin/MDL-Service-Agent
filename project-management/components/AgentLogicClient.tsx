"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale } from "@/components/LocaleProvider";
import { AGENT_STATUSES, type Agent, type AgentStatus, statusBadgeClass } from "@/lib/types";

type Props = {
  agent: Agent;
};

function agentStatusLabel(status: AgentStatus, t: ReturnType<typeof useLocale>["t"]) {
  const map = {
    개발중: t.agents.statusDev,
    테스트중: t.agents.statusTest,
    배포완료: t.agents.statusDone,
  };
  return map[status];
}

export default function AgentLogicClient({ agent }: Props) {
  const router = useRouter();
  const { t } = useLocale();
  const [form, setForm] = useState({
    name: agent.name,
    description: agent.description,
    status: agent.status,
    logic: agent.logic,
  });
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSaved(false);

    const res = await fetch("/api/agents", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, id: agent.id, createdAt: agent.createdAt }),
    });

    if (!res.ok) {
      setError(t.agents.saveError);
      return;
    }

    setSaved(true);
    router.refresh();
  }

  async function handleDelete() {
    if (!confirm(t.agents.confirmDelete)) return;
    await fetch("/api/agents", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: agent.id }),
    });
    router.push("/agents");
    router.refresh();
  }

  return (
    <form className="form-panel" onSubmit={handleSubmit}>
      <div className="form-grid">
        <div className="form-field">
          <label htmlFor="logic-name">{t.agents.name}</label>
          <input
            id="logic-name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
        </div>
        <div className="form-field">
          <label htmlFor="logic-status">{t.agents.status}</label>
          <select
            id="logic-status"
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
        <label htmlFor="logic-desc">{t.agents.description}</label>
        <input
          id="logic-desc"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
      </div>
      <div className="form-field" style={{ marginTop: "0.75rem" }}>
        <label htmlFor="logic-body">{t.agents.logicLabel}</label>
        <textarea
          id="logic-body"
          className="logic-textarea"
          value={form.logic}
          onChange={(e) => setForm({ ...form, logic: e.target.value })}
          placeholder={t.agents.logicPlaceholder}
          rows={14}
        />
      </div>
      {error && <p className="form-error">{error}</p>}
      {saved && <p className="form-success">{t.agents.saved}</p>}
      <div className="btn-row form-panel-actions">
        <button type="button" className="btn btn-danger" onClick={handleDelete}>
          {t.agents.delete}
        </button>
        <div className="btn-row" style={{ marginLeft: "auto" }}>
          <Link href="/agents" className="btn">
            {t.agents.backToList}
          </Link>
          <Link href={`/agents/${agent.id}/flow`} className="btn">
            {t.agents.tabFlow}
          </Link>
          <Link href={`/agents/${agent.id}/playground`} className="btn">
            {t.agents.goPlayground}
          </Link>
          <button type="submit" className="btn btn-primary">
            {t.agents.update}
          </button>
        </div>
      </div>
    </form>
  );
}
