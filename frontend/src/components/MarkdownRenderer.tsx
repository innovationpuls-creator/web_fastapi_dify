import {
  Children,
  isValidElement,
  memo,
  useEffect,
  useState,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from "react";
import { Check, Copy } from "lucide-react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

type MarkdownRendererProps = {
  content: string;
  toneClassName?: string;
  variant?: "default" | "compact";
  isStreaming?: boolean;
};

type MarkdownCodeProps = ComponentPropsWithoutRef<"code"> & {
  inline?: boolean;
  node?: unknown;
  children?: ReactNode;
};

type MarkdownPreProps = ComponentPropsWithoutRef<"pre"> & {
  node?: unknown;
  children?: ReactNode;
};

const extractCodeLanguage = (className?: string) => {
  const match = /language-([\w-]+)/i.exec(className || "");
  return match?.[1] || "code";
};

const extractTextContent = (node: ReactNode): string => {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }

  if (Array.isArray(node)) {
    return node.map((child) => extractTextContent(child)).join("");
  }

  if (isValidElement(node)) {
    return extractTextContent(node.props.children);
  }

  return "";
};

const copyTextToClipboard = async (value: string) => {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Fall through to the legacy textarea-based copy path.
  }

  try {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "true");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(textarea);
    return copied;
  } catch {
    return false;
  }
};

const stabilizeStreamingMarkdown = (content: string) => {
  const fenceCount = (content.match(/(^|\n)```/g) || []).length;
  if (fenceCount % 2 === 0) {
    return content;
  }

  return `${content}\n\`\`\``;
};

const VARIANT_STYLES = {
  default: {
    heading1:
      "mb-5 mt-2 text-[2rem] font-semibold leading-[1.15] tracking-[-0.04em] text-current first:mt-0",
    heading2:
      "mb-4 mt-8 text-[1.45rem] font-semibold leading-[1.2] tracking-[-0.03em] text-current first:mt-0",
    heading3:
      "mb-3 mt-6 text-[1.1rem] font-semibold leading-[1.28] tracking-[-0.02em] text-current first:mt-0",
    paragraph: "mb-4 text-[16px] leading-8 tracking-[-0.01em] text-current last:mb-0",
    list: "mb-5 space-y-2.5 pl-6 text-[16px] leading-8 text-current",
    blockquote: "mb-5 border-l-2 border-white/10 pl-4 text-zinc-300",
    tableShell: "mb-5 overflow-x-auto rounded-[1rem] border border-white/[0.08]",
    table: "min-w-full border-collapse bg-white/[0.02] text-left text-[14px] text-zinc-100",
    th: "border-b border-white/[0.08] px-4 py-3 text-[11px] uppercase tracking-[0.18em] text-zinc-400",
    td: "border-b border-white/[0.06] px-4 py-3 align-top text-[14px] leading-7 text-zinc-200",
    rule: "my-5 border-white/[0.08]",
    codeShell:
      "mb-5 overflow-hidden rounded-[1rem] border border-white/[0.08] bg-[#0b0d11] shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]",
    codeHeader:
      "flex items-center justify-between gap-3 border-b border-white/[0.06] bg-white/[0.03] px-4 py-2",
    codeLabel: "text-[11px] uppercase tracking-[0.2em] text-zinc-500",
    codeAction:
      "inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.04] px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-400 transition hover:border-white/[0.14] hover:bg-white/[0.07] hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20",
    pre: "overflow-x-auto px-4 py-4",
    inlineCode:
      "rounded-md border border-white/[0.08] bg-white/[0.06] px-1.5 py-0.5 font-mono text-[0.92em] text-zinc-100",
    blockCode: "font-mono text-[13px] leading-7 text-zinc-100",
  },
  compact: {
    heading1: "mb-3 text-[1.15rem] font-semibold leading-tight tracking-[-0.03em] text-current",
    heading2: "mb-3 text-[1rem] font-semibold leading-tight tracking-[-0.02em] text-current",
    heading3: "mb-2 text-[0.95rem] font-semibold leading-tight tracking-[-0.015em] text-current",
    paragraph: "mb-3 text-[13px] leading-7 tracking-[-0.01em] text-current last:mb-0 sm:text-[14px]",
    list: "mb-3 space-y-1.5 pl-5 text-[13px] leading-7 text-current sm:text-[14px]",
    blockquote: "mb-3 border-l border-white/10 pl-3 text-zinc-300/90",
    tableShell: "mb-4 overflow-x-auto rounded-[0.9rem] border border-white/[0.08]",
    table: "min-w-full border-collapse bg-white/[0.02] text-left text-[12px] text-zinc-100 sm:text-[13px]",
    th: "border-b border-white/[0.08] px-3 py-2 text-[10px] uppercase tracking-[0.16em] text-zinc-500",
    td: "border-b border-white/[0.06] px-3 py-2 align-top text-[12px] leading-6 text-zinc-200 sm:text-[13px]",
    rule: "my-4 border-white/[0.08]",
    codeShell:
      "mb-4 overflow-hidden rounded-[0.9rem] border border-white/[0.08] bg-[#0b0d11] shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]",
    codeHeader:
      "flex items-center justify-between gap-3 border-b border-white/[0.06] bg-white/[0.03] px-3 py-2",
    codeLabel: "text-[10px] uppercase tracking-[0.18em] text-zinc-500",
    codeAction:
      "inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.04] px-2 py-1 text-[9px] font-medium uppercase tracking-[0.12em] text-zinc-400 transition hover:border-white/[0.14] hover:bg-white/[0.07] hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/20",
    pre: "overflow-x-auto px-3 py-3",
    inlineCode:
      "rounded-md border border-white/[0.08] bg-white/[0.06] px-1.5 py-0.5 font-mono text-[0.9em] text-zinc-100",
    blockCode: "font-mono text-[12px] leading-6 text-zinc-100 sm:text-[13px]",
  },
} as const;

type CodeBlockFrameProps = {
  children: ReactNode;
  codeText: string;
  language: string;
  codeShellClassName: string;
  codeHeaderClassName: string;
  codeLabelClassName: string;
  codeActionClassName: string;
  preClassName: string;
};

const CodeBlockFrame = ({
  children,
  codeText,
  language,
  codeShellClassName,
  codeHeaderClassName,
  codeLabelClassName,
  codeActionClassName,
  preClassName,
}: CodeBlockFrameProps) => {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (copyState === "idle") {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      setCopyState("idle");
    }, 1800);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [copyState]);

  const handleCopy = async () => {
    if (!codeText.trim()) {
      setCopyState("failed");
      return;
    }

    const copied = await copyTextToClipboard(codeText);
    setCopyState(copied ? "copied" : "failed");
  };

  return (
    <div className={codeShellClassName}>
      <div className={codeHeaderClassName}>
        <div className={codeLabelClassName}>{language}</div>
        <button
          type="button"
          onClick={handleCopy}
          className={codeActionClassName}
          aria-label={copyState === "copied" ? "Code copied" : "Copy code"}
        >
          {copyState === "copied" ? <Check className="h-3.5 w-3.5" strokeWidth={2} /> : <Copy className="h-3.5 w-3.5" strokeWidth={2} />}
          <span>{copyState === "copied" ? "Copied" : copyState === "failed" ? "Retry" : "Copy"}</span>
        </button>
      </div>
      <pre className={preClassName}>{children}</pre>
    </div>
  );
};

const MarkdownRendererComponent = ({
  content,
  toneClassName = "text-white",
  variant = "default",
  isStreaming = false,
}: MarkdownRendererProps) => {
  const styles = VARIANT_STYLES[variant];
  const renderedContent = isStreaming ? stabilizeStreamingMarkdown(content) : content;
  const components: Components = {
    h1: ({ children }) => (
      <h1 className={styles.heading1}>{children}</h1>
    ),
    h2: ({ children }) => (
      <h2 className={styles.heading2}>{children}</h2>
    ),
    h3: ({ children }) => (
      <h3 className={styles.heading3}>{children}</h3>
    ),
    p: ({ children }) => <p className={styles.paragraph}>{children}</p>,
    ul: ({ children }) => <ul className={`list-disc ${styles.list}`}>{children}</ul>,
    ol: ({ children }) => <ol className={`list-decimal ${styles.list}`}>{children}</ol>,
    li: ({ children }) => <li className="pl-1 marker:text-zinc-500">{children}</li>,
    blockquote: ({ children }) => (
      <blockquote className={styles.blockquote}>{children}</blockquote>
    ),
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="text-[#c9d8ff] underline decoration-white/20 underline-offset-4 transition hover:text-white"
      >
        {children}
      </a>
    ),
    table: ({ children }) => (
      <div className={styles.tableShell}>
        <table className={styles.table}>{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="bg-white/[0.04]">{children}</thead>,
    th: ({ children }) => <th className={styles.th}>{children}</th>,
    td: ({ children }) => <td className={styles.td}>{children}</td>,
    hr: () => <hr className={styles.rule} />,
    pre: ({ children }: MarkdownPreProps) => {
      const onlyChild = Children.count(children) === 1 ? Children.only(children) : null;
      const language =
        isValidElement(onlyChild) && typeof onlyChild.props.className === "string"
          ? extractCodeLanguage(onlyChild.props.className)
          : "code";
      const codeText = extractTextContent(
        isValidElement(onlyChild) ? onlyChild.props.children : children,
      );

      return (
        <CodeBlockFrame
          codeText={codeText}
          language={language}
          codeShellClassName={styles.codeShell}
          codeHeaderClassName={styles.codeHeader}
          codeLabelClassName={styles.codeLabel}
          codeActionClassName={styles.codeAction}
          preClassName={styles.pre}
        >
          {children}
        </CodeBlockFrame>
      );
    },
    code: ({ inline, className, children, ...props }: MarkdownCodeProps) => {
      const value = String(children).replace(/\n$/, "");

      if (inline) {
        return (
          <code {...props} className={styles.inlineCode}>
            {value}
          </code>
        );
      }

      return (
        <code {...props} className={`${styles.blockCode} ${className || ""}`}>
          {value}
        </code>
      );
    },
  };

  return (
    <div className={`min-w-0 ${toneClassName}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {renderedContent}
      </ReactMarkdown>
      {isStreaming ? (
        <div className="mt-1">
          <span className="assistant-cursor h-6 align-middle opacity-80" aria-hidden="true" />
        </div>
      ) : null}
    </div>
  );
};

const MarkdownRenderer = memo(MarkdownRendererComponent);

MarkdownRenderer.displayName = "MarkdownRenderer";

export default MarkdownRenderer;
