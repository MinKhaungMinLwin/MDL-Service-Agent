import { redirect } from "next/navigation";

type Props = {
  params: Promise<{ id: string }>;
};

export default async function AgentDetailPage({ params }: Props) {
  const { id } = await params;
  redirect(`/agents/${id}/logic`);
}
