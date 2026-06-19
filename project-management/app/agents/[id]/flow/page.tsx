import { notFound } from "next/navigation";
import AgentFlowClient from "@/components/AgentFlowClient";
import { readAgents } from "@/lib/agent-utils";

type Props = {
  params: Promise<{ id: string }>;
};

export default async function AgentFlowPage({ params }: Props) {
  const { id } = await params;
  const agents = await readAgents();
  const agent = agents.find((entry) => entry.id === id);
  if (!agent) notFound();

  return <AgentFlowClient agent={agent} />;
}
