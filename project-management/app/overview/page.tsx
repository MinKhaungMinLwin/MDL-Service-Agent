import AppShell from "@/components/AppShell";
import ContentPage from "@/components/ContentPage";
import { loadContentBoth } from "@/lib/content";

export default async function OverviewIndexPage() {
  const initial = await loadContentBoth("overview/index");

  return (
    <AppShell section="overview">
      <ContentPage contentPath="overview/index" initial={initial} />
    </AppShell>
  );
}
