"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale } from "@/components/LocaleProvider";
import type { Agent } from "@/lib/types";

type Props = {
  agent: Agent;
};

export default function AgentFlowClient({ agent }: Props) {
  const router = useRouter();
  const { t } = useLocale();
  const [flow, setFlow] = useState(agent.flow);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSaved(false);

    const res = await fetch("/api/agents", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...agent,
        flow,
      }),
    });

    if (!res.ok) {
      setError(t.agents.saveError);
      return;
    }

    setSaved(true);
    router.refresh();
  }

  return (
    <form className="form-panel" onSubmit={handleSubmit}>
      <p className="field-hint" style={{ marginBottom: "0.75rem" }}>
        {t.agents.flowHint}
      </p>
      <div className="form-field">
        <label htmlFor="agent-flow">{t.agents.flowLabel}</label>
        <textarea
          id="agent-flow"
          className="logic-textarea"
          value={flow}
          onChange={(e) => setFlow(e.target.value)}
          placeholder={t.agents.flowPlaceholder}
          rows={16}
        />
      </div>
      {error && <p className="form-error">{error}</p>}
      {saved && <p className="form-success">{t.agents.saved}</p>}
      <div className="btn-row form-panel-actions">
        <Link href={`/agents/${agent.id}/logic`} className="btn">
          {t.agents.tabLogic}
        </Link>
        <Link href={`/agents/${agent.id}/playground`} className="btn">
          {t.agents.tabPlayground}
        </Link>
        <button type="submit" className="btn btn-primary" style={{ marginLeft: "auto" }}>
          {t.agents.update}
        </button>
      </div>
    </form>
  );
}
