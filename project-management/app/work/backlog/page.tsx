import AppShell from "@/components/AppShell";
import WorkBacklogClient from "@/components/WorkBacklogClient";
import { readJsonFile, readWorkItems } from "@/lib/storage";
import { toPublicUser } from "@/lib/user-utils";
import type { UserRecord } from "@/lib/types";

export default async function WorkBacklogPage() {
  const [items, userRecords] = await Promise.all([
    readWorkItems(),
    readJsonFile<UserRecord[]>("users.json", []),
  ]);
  const users = userRecords.map(toPublicUser);

  return (
    <AppShell section="work">
      <header className="page-header">
        <h1>Backlog</h1>
        <p>개발자에게 할당할 작업을 관리합니다.</p>
      </header>
      <WorkBacklogClient initialItems={items} initialUsers={users} />
    </AppShell>
  );
}
