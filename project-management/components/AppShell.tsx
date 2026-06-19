import Header from "@/components/Header";
import Sidebar from "@/components/Sidebar";
import type { SectionId } from "@/lib/navigation";

type Props = {
  section: SectionId;
  children: React.ReactNode;
  wide?: boolean;
  hideSidebar?: boolean;
};

export default function AppShell({ section, children, wide, hideSidebar }: Props) {
  return (
    <>
      <Header />
      <div className="layout">
        {!hideSidebar && <Sidebar section={section} />}
        <main
          className={[
            "content",
            wide ? "content-wide" : "",
            hideSidebar ? "content-full" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          {children}
        </main>
      </div>
    </>
  );
}
