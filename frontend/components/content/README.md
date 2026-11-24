# Content page components

The frame and pieces of the public content pages (about, docs, FAQ, support, contact, status) and the layout of the legal pages (privacy, cookies, terms, security, accessibility), whose text is in `content/legal`.

| File | Description |
|---|---|
| faq.tsx | The FAQ questions and answers, the five the home page shows and their FAQPage data |
| JsonLd.tsx | Structured data for search engines, only for what the page shows |
| Breadcrumbs.tsx | Home, the section and the current page, with BreadcrumbList data |
| PageShell.tsx | The container, the `SiteHeading` and the content on one left edge |
| Section.tsx | A heading, spacing and a hairline rule. Never a box |
| Prose.tsx | Running text in a column of at most 72 characters, plus the list and code pieces |
| TextLink.tsx | A link in running text: always underlined, an external one opens in a new tab with a spoken note |
| StatusCheck.tsx | Asks the API's public `/status` route from the visitor's browser |
| LegalPage.tsx | Lays out a legal page from a Markdown file in `content/legal`: contents list, prose, real tables, marked placeholders. It holds no legal text |
| legal.ts | Shared links for the content pages |
