type Props = { html: string };

export default function LegacyHtmlContent({ html }: Props) {
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}
