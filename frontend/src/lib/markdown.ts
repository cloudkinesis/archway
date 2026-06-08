import DOMPurify from "dompurify";
import { marked } from "marked";

marked.use({ async: false, gfm: true });

export function sanitizeMarkdown(markdown: string): string {
  const html = marked.parse(markdown, { async: false }) as string;
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    ALLOWED_ATTR: ["href", "title", "target", "rel"]
  });
}

