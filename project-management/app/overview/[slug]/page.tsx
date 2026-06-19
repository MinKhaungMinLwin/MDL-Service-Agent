import { notFound } from "next/navigation";
import AppShell from "@/components/AppShell";
import ContentPage from "@/components/ContentPage";
import { loadContentBoth } from "@/lib/content";
import { OVERVIEW_SLUGS } from "@/lib/navigation";

type Props = { params: Promise<{ slug: string }> };

export function generateStaticParams() {
  return OVERVIEW_SLUGS.filter((s) => s.slug).map((s) => ({ slug: s.slug }));
}

export default async function OverviewSlugPage({ params }: Props) {
  const { slug } = await params;
  const entry = OVERVIEW_SLUGS.find((s) => s.slug === slug);
  if (!entry) notFound();

  const contentPath = `overview/${entry.file}`;
  const initial = await loadContentBoth(contentPath);

  return (
    <AppShell section="overview">
      <ContentPage contentPath={contentPath} initial={initial} />
    </AppShell>
  );
}
