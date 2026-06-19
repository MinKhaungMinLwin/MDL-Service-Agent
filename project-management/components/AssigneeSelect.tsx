import type { User } from "@/lib/types";

type Props = {
  users: User[];
  value: string;
  onChange: (assignee: string) => void;
  selectLabel: string;
  noUsersHint?: string;
};

export default function AssigneeSelect({
  users,
  value,
  onChange,
  selectLabel,
  noUsersHint,
}: Props) {
  const matched = users.find((user) => user.name === value || user.email === value);
  const selectValue = matched?.id ?? (value ? "__current__" : "");

  if (users.length === 0) {
    return (
      <>
        <select disabled>
          <option>{selectLabel}</option>
        </select>
        {noUsersHint && <p className="field-hint">{noUsersHint}</p>}
      </>
    );
  }

  return (
    <select
      value={selectValue}
      onChange={(e) => {
        const id = e.target.value;
        if (!id) {
          onChange("");
          return;
        }
        if (id === "__current__") return;
        const user = users.find((entry) => entry.id === id);
        onChange(user?.name ?? "");
      }}
    >
      <option value="">{selectLabel}</option>
      {value && !matched && (
        <option value="__current__">{value}</option>
      )}
      {users.map((user) => (
        <option key={user.id} value={user.id}>
          {user.name} ({user.email})
        </option>
      ))}
    </select>
  );
}
