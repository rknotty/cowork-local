import { memo } from "react";
import type { ReactElement } from "react";
import Markdown from "react-markdown";
import type { Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

interface MarkdownViewProps {
  text: string;
}

const REMARK_PLUGINS = [remarkGfm];
const REHYPE_PLUGINS = [rehypeHighlight];

const MARKDOWN_COMPONENTS: Components = {
  // Model output must not trigger network requests, so only inline data: images
  // are rendered. Anything else is shown as its alt text.
  img: ({ src, alt }) => {
    if (typeof src === "string" && src.startsWith("data:image/")) {
      return <img src={src} alt={alt ?? ""} />;
    }
    return (
      <span className="markdown-blocked-image">[Image not loaded: {alt ?? "no description"}]</span>
    );
  },
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
};

function MarkdownViewInner({ text }: MarkdownViewProps): ReactElement {
  return (
    <div className="markdown">
      <Markdown
        remarkPlugins={REMARK_PLUGINS}
        rehypePlugins={REHYPE_PLUGINS}
        components={MARKDOWN_COMPONENTS}
      >
        {text}
      </Markdown>
    </div>
  );
}

/**
 * Renders markdown with GitHub-flavoured extensions and bundled syntax
 * highlighting. Raw HTML in the source is not rendered.
 */
export const MarkdownView = memo(MarkdownViewInner);
