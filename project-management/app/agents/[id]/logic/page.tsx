import { notFound } from "next/navigation";
import AgentLogicClient from "@/components/AgentLogicClient";
import { readAgents } from "@/lib/agent-utils";

type Props = {
  params: Promise<{ id: string }>;
};

export default async function AgentLogicPage({ params }: Props) {
  const { id } = await params;
  const agents = await readAgents();
  const agent = agents.find((entry) => entry.id === id);
  if (!agent) notFound();

  return <AgentLogicClient agent={agent} />;
}
