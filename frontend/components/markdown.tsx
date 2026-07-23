import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Markdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ ...props }) => <p className="mb-2 last:mb-0 leading-relaxed" {...props} />,
        ul: ({ ...props }) => <ul className="mb-2 list-disc pl-5 last:mb-0" {...props} />,
        ol: ({ ...props }) => <ol className="mb-2 list-decimal pl-5 last:mb-0" {...props} />,
        li: ({ ...props }) => <li className="mb-1" {...props} />,
        a: ({ ...props }) => (
          <a className="underline underline-offset-2 hover:no-underline" target="_blank" rel="noreferrer" {...props} />
        ),
        strong: ({ ...props }) => <strong className="font-semibold" {...props} />,
        code: ({ className, children, ...props }) => {
          const isBlock = /language-/.test(className ?? "");
          return isBlock ? (
            <code className="block whitespace-pre-wrap rounded-md bg-black/10 p-2 text-sm" {...props}>
              {children}
            </code>
          ) : (
            <code className="rounded bg-black/10 px-1 py-0.5 text-sm" {...props}>
              {children}
            </code>
          );
        },
        pre: ({ ...props }) => <pre className="mb-2 overflow-x-auto last:mb-0" {...props} />,
        h1: ({ ...props }) => <h1 className="mb-2 text-lg font-semibold" {...props} />,
        h2: ({ ...props }) => <h2 className="mb-2 text-base font-semibold" {...props} />,
        h3: ({ ...props }) => <h3 className="mb-2 text-sm font-semibold" {...props} />,
        table: ({ ...props }) => (
          <div className="mb-2 overflow-x-auto last:mb-0">
            <table className="border-collapse text-sm" {...props} />
          </div>
        ),
        th: ({ ...props }) => <th className="border px-2 py-1 text-left font-medium" {...props} />,
        td: ({ ...props }) => <td className="border px-2 py-1" {...props} />,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
