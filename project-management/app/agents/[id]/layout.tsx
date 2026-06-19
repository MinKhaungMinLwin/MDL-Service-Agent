import { notFound } from "next/navigation";
import AppShell from "@/components/AppShell";
import AgentDetailTabs from "@/components/AgentDetailTabs";
import { readAgents } from "@/lib/agent-utils";
import { statusBadgeClass } from "@/lib/types";

type Props = {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
};

export default async function AgentDetailLayout({ children, params }: Props) {
  const { id } = await params;
  const agents = await readAgents();
  const agent = agents.find((entry) => entry.id === id);
  if (!agent) notFound();

  return (
    <AppShell section="agents">
      <div className="detail-header">
        <div className="detail-header-row">
          <h1 className="detail-title">{agent.name}</h1>
          <span className={`status-badge ${statusBadgeClass(agent.status)}`}>{agent.status}</span>
        </div>
        {agent.description && <p className="detail-meta">{agent.description}</p>}
      </div>
      <AgentDetailTabs agentId={id} />
      {children}
    </AppShell>
  );
}
