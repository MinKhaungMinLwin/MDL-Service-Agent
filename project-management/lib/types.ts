export type TaskStatus = "완료" | "진행중" | "진행예정";

export type WorkItem = {
  id: string;
  title: string;
  status: TaskStatus;
  assignee: string;
  description: string;
  scheduleStart: string;
  scheduleEnd: string;
};

export type BacklogItem = {
  id: string;
  l1: string;
  l2: string;
  task: string;
  status: TaskStatus;
  deliverable: string;
  scheduleStart: string;
  scheduleEnd: string;
};

export type IssueStatus = "Open" | "In Progress" | "Done" | "Blocked";
export type IssuePriority = "High" | "Medium" | "Low";

export type Issue = {
  id: string;
  title: string;
  status: IssueStatus;
  priority: IssuePriority;
  assignee: string;
  description: string;
  createdAt: string;
};

export type User = {
  id: string;
  email: string;
  name: string;
  createdAt: string;
};

export type UserRecord = User & {
  password: string;
};

export type AgentStatus = "개발중" | "테스트중" | "배포완료";

export type Agent = {
  id: string;
  name: string;
  description: string;
  status: AgentStatus;
  logic: string;
  flow: string;
  createdAt: string;
  updatedAt: string;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export const TASK_STATUSES: TaskStatus[] = ["진행예정", "진행중", "완료"];
export const AGENT_STATUSES: AgentStatus[] = ["개발중", "테스트중", "배포완료"];
export const ISSUE_STATUSES: IssueStatus[] = ["Open", "In Progress", "Done", "Blocked"];
export const ISSUE_PRIORITIES: IssuePriority[] = ["High", "Medium", "Low"];

export function statusBadgeClass(status: TaskStatus | string): string {
  const map: Record<string, string> = {
    완료: "status-done",
    진행중: "status-progress",
    진행예정: "status-todo",
    Open: "status-todo",
    "In Progress": "status-progress",
    Done: "status-done",
    Blocked: "status-blocked",
    개발중: "status-progress",
    테스트중: "status-todo",
    배포완료: "status-done",
  };
  return map[status] ?? "";
}
