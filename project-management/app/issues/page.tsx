import AppShell from "@/components/AppShell";
import ContentPage from "@/components/ContentPage";
import IssuesClient from "@/components/IssuesClient";
import { loadContentBoth } from "@/lib/content";
import { readJsonFile } from "@/lib/storage";
import type { Issue } from "@/lib/types";

export default async function IssuesPage() {
  const [items, initial] = await Promise.all([
    readJsonFile<Issue[]>("issues.json", []),
    loadContentBoth("issues"),
  ]);

  return (
    <AppShell section="issues">
      <ContentPage contentPath="issues" initial={initial} />
      <IssuesClient initialItems={items} />
    </AppShell>
  );
}
