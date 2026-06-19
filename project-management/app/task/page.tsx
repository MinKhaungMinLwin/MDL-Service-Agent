import AppShell from "@/components/AppShell";
import BacklogClient from "@/components/BacklogClient";
import ContentPage from "@/components/ContentPage";
import { loadContentBoth } from "@/lib/content";
import { readBacklogItems } from "@/lib/storage";

export default async function TaskPage() {
  const [itemsKo, initial] = await Promise.all([
    readBacklogItems("ko"),
    loadContentBoth("ia"),
  ]);

  return (
    <AppShell section="backlog">
      <ContentPage contentPath="ia" initial={initial} />
      <BacklogClient initialItems={itemsKo} />
    </AppShell>
  );
}
