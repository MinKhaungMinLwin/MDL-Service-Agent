import { redirect } from "next/navigation";

type Props = {
  params: Promise<{ id: string }>;
};

export default async function TaskDetailPage({ params }: Props) {
  const { id } = await params;
  redirect(`/task/${id}/info`);
}
