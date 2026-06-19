import type { BacklogItem, TaskStatus } from "@/lib/types";
import { TASK_STATUSES } from "@/lib/types";
import { taskStatusLabel, type Locale } from "@/lib/i18n";

type TaskFormProps = {
  form: Omit<BacklogItem, "id">;
  setForm: React.Dispatch<React.SetStateAction<Omit<BacklogItem, "id">>>;
  items: BacklogItem[];
  locale: Locale;
  labels: {
    l1: string;
    selectL1: string;
    l2: string;
    selectL2: string;
    status: string;
    scheduleStart: string;
    scheduleEnd: string;
    task: string;
    deliverable: string;
  };
};

function getL2Options(items: BacklogItem[], l1: string, includeL2?: string) {
  const set = new Set(
    items.filter((item) => item.l1 === l1).map((item) => item.l2).filter(Boolean),
  );
  if (includeL2) set.add(includeL2);
  return [...set].sort();
}

export default function TaskFormFields({ form, setForm, items, locale, labels }: TaskFormProps) {
  const l1Options = [
    ...new Set([...items.map((item) => item.l1), form.l1].filter(Boolean)),
  ].sort();
  const l2Options = form.l1 ? getL2Options(items, form.l1, form.l2) : [];

  return (
    <>
      <div className="form-grid">
        <div className="form-field">
          <label>{labels.l1}</label>
          <select
            value={form.l1}
            onChange={(e) => {
              const l1 = e.target.value;
              const nextL2 = getL2Options(items, l1)[0] ?? "";
              setForm({ ...form, l1, l2: nextL2 });
            }}
            required
          >
            {!form.l1 && (
              <option value="" disabled>
                {labels.selectL1}
              </option>
            )}
            {l1Options.map((l1) => (
              <option key={l1} value={l1}>
                {l1}
              </option>
            ))}
          </select>
        </div>
        <div className="form-field">
          <label>{labels.l2}</label>
          <select
            value={form.l2}
            onChange={(e) => setForm({ ...form, l2: e.target.value })}
            required
            disabled={!form.l1}
          >
            {!form.l2 && (
              <option value="" disabled>
                {labels.selectL2}
              </option>
            )}
            {l2Options.map((l2) => (
              <option key={l2} value={l2}>
                {l2}
              </option>
            ))}
          </select>
        </div>
        <div className="form-field">
          <label>{labels.status}</label>
          <select
            value={form.status}
            onChange={(e) => setForm({ ...form, status: e.target.value as TaskStatus })}
          >
            {TASK_STATUSES.map((s) => (
              <option key={s} value={s}>
                {taskStatusLabel(locale, s)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="form-grid" style={{ marginBottom: "0.75rem" }}>
        <div className="form-field">
          <label>{labels.scheduleStart}</label>
          <input
            type="date"
            value={form.scheduleStart}
            onChange={(e) => setForm({ ...form, scheduleStart: e.target.value })}
          />
        </div>
        <div className="form-field">
          <label>{labels.scheduleEnd}</label>
          <input
            type="date"
            value={form.scheduleEnd}
            min={form.scheduleStart || undefined}
            onChange={(e) => setForm({ ...form, scheduleEnd: e.target.value })}
          />
        </div>
      </div>
      <div className="form-field" style={{ marginBottom: "0.75rem" }}>
        <label>{labels.task}</label>
        <input
          value={form.task}
          onChange={(e) => setForm({ ...form, task: e.target.value })}
          required
        />
      </div>
      <div className="form-field">
        <label>{labels.deliverable}</label>
        <input
          value={form.deliverable}
          onChange={(e) => setForm({ ...form, deliverable: e.target.value })}
        />
      </div>
    </>
  );
}
