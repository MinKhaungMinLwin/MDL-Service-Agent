import { notFound } from "next/navigation";
import AgentPlayground from "@/components/AgentPlayground";
import { readAgents } from "@/lib/agent-utils";

type Props = {
  params: Promise<{ id: string }>;
};

export default async function AgentPlaygroundPage({ params }: Props) {
  const { id } = await params;
  const agents = await readAgents();
  const agent = agents.find((entry) => entry.id === id);
  if (!agent) notFound();

  return <AgentPlayground agent={agent} />;
}
