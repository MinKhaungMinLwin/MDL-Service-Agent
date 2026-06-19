import AppShell from "@/components/AppShell";
import AgentsClient from "@/components/AgentsClient";
import { readAgents } from "@/lib/agent-utils";

export default async function AgentsPage() {
  const agents = await readAgents();

  return (
    <AppShell section="agents">
      <header className="page-header">
        <h1>Agent</h1>
        <p>개발 중인 에이전트를 등록하고 플레이그라운드에서 테스트합니다.</p>
      </header>
      <AgentsClient initialAgents={agents} />
    </AppShell>
  );
}
