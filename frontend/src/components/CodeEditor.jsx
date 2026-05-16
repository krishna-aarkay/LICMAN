import { useEffect, useRef } from "react";

/**
 * Minimal monospace editor with line numbers.
 * No syntax engine — we color the rendered overlay text by simple regex per line.
 */
export const CodeEditor = ({ value, onChange, language = "license", testId, height = "60vh" }) => {
  const taRef = useRef(null);
  const linesRef = useRef(null);
  const overlayRef = useRef(null);

  const lines = (value || "").split("\n");

  const onScroll = () => {
    if (linesRef.current && taRef.current) {
      linesRef.current.scrollTop = taRef.current.scrollTop;
    }
    if (overlayRef.current && taRef.current) {
      overlayRef.current.scrollTop = taRef.current.scrollTop;
      overlayRef.current.scrollLeft = taRef.current.scrollLeft;
    }
  };

  useEffect(() => {
    onScroll();
  }, [value]);

  const highlight = (text) => {
    const keywords =
      language === "options"
        ? /\b(RESERVE|EXCLUDE|INCLUDE|INCLUDEALL|EXCLUDEALL|GROUP|HOST_GROUP|MAX|TIMEOUT|TIMEOUTALL|REPORTLOG|DEBUGLOG|NOLOG|BORROW_LOWWATER|LINGER)\b/g
        : /\b(SERVER|VENDOR|FEATURE|INCREMENT|USE_SERVER|PACKAGE|UPGRADE)\b/g;
    const targets = /\b(USER|HOST|GROUP|DISPLAY|INTERNET|PROJECT)\b/g;

    return text.split("\n").map((ln, i) => {
      if (ln.trim().startsWith("#")) {
        return (
          <div key={i} className="text-[#4b5563] italic">
            {ln || "\u00A0"}
          </div>
        );
      }
      let html = ln.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
      html = html.replace(keywords, (m) => `<span class="kw">${m}</span>`);
      html = html.replace(targets, (m) => `<span class="tg">${m}</span>`);
      html = html.replace(/"([^"]*)"/g, '<span class="str">"$1"</span>');
      html = html.replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="num">$1</span>');
      return (
        <div
          key={i}
          dangerouslySetInnerHTML={{ __html: html || "\u00A0" }}
        />
      );
    });
  };

  return (
    <div
      className="relative bg-[#000] border border-[#222] rounded-sm font-mono text-xs flex overflow-hidden"
      style={{ height }}
      data-testid={testId}
    >
      {/* line numbers */}
      <div
        ref={linesRef}
        className="bg-[#0a0a0a] border-r border-[#222] text-right py-3 px-3 text-[#4b5563] select-none overflow-hidden tabular-nums"
        style={{ minWidth: 48, lineHeight: "1.5rem" }}
      >
        {lines.map((_, i) => (
          <div key={i} className="leading-6">
            {i + 1}
          </div>
        ))}
      </div>

      {/* code area */}
      <div className="relative flex-1 overflow-hidden">
        <div
          ref={overlayRef}
          className="absolute inset-0 py-3 px-3 overflow-auto pointer-events-none whitespace-pre"
          style={{ lineHeight: "1.5rem" }}
        >
          <style>{`
            .kw { color: #10b981; font-weight: 600; }
            .tg { color: #3b82f6; font-weight: 500; }
            .str { color: #f59e0b; }
            .num { color: #a78bfa; }
          `}</style>
          {highlight(value || "")}
        </div>
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onScroll={onScroll}
          spellCheck={false}
          className="absolute inset-0 w-full h-full bg-transparent text-transparent caret-emerald-400 resize-none p-3 outline-none selection:bg-emerald-700/40 whitespace-pre overflow-auto"
          style={{ lineHeight: "1.5rem", fontFamily: "JetBrains Mono, monospace", fontSize: "12px" }}
          data-testid={`${testId}-textarea`}
        />
      </div>
    </div>
  );
};

export default CodeEditor;
