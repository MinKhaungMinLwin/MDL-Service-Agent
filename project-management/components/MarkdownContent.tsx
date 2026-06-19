"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Props = { source: string };

function extractHtml(source: string): string | null {
  const trimmed = source.trimStart();
  if (trimmed.startsWith("<!-- html -->")) {
    return trimmed.replace(/^<!-- html -->\s*/, "");
  }
  return null;
}

export default function MarkdownContent({ source }: Props) {
  const html = extractHtml(source);

  if (html) {
    return <div className="markdown-body" dangerouslySetInnerHTML={{ __html: html }} />;
  }

  if (!source.trim()) {
    return null;
  }

  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{source}</ReactMarkdown>
    </div>
  );
}
