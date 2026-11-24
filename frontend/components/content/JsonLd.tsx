// structured data for search engines. It only ever describes what the same page shows, so it can never claim more than a
// reader can see. A data block is never run as script, so the content security policy does not have to allow it. The
// "<" escape stops a value from closing the tag early.
export default function JsonLd({ data }: { data: object }) {
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, '\\u003c') }} />;
}
