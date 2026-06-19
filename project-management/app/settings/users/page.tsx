import AppShell from "@/components/AppShell";
import UsersClient from "@/components/UsersClient";
import { readJsonFile } from "@/lib/storage";
import { toPublicUser } from "@/lib/user-utils";
import type { UserRecord } from "@/lib/types";

export default async function UserSettingsPage() {
  const records = await readJsonFile<UserRecord[]>("users.json", []);
  const users = records.map(toPublicUser);

  return (
    <AppShell section="settings">
      <UsersClient initialUsers={users} />
    </AppShell>
  );
}
