import { useEffect, useRef } from "react";
import { Terminal } from "xterm";
import { FitAddon } from "xterm-addon-fit";
import "xterm/css/xterm.css";

interface Props {
  output: string;
  onInput: (data: string) => void;
  onResize: (cols: number, rows: number) => void;
}

export default function XtermView({ output, onInput, onResize }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const lastWrittenRef = useRef<number>(0);

  useEffect(() => {
    if (!containerRef.current) return;
    const term = new Terminal({
      convertEol: false,
      cursorBlink: true,
      fontFamily: "Cascadia Code, Consolas, monospace",
      fontSize: 13,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    fit.fit();
    onResize(term.cols, term.rows);
    term.onData((d) => onInput(d));
    termRef.current = term;
    fitRef.current = fit;

    const ro = new ResizeObserver(() => {
      fit.fit();
      onResize(term.cols, term.rows);
    });
    ro.observe(containerRef.current);
    return () => {
      ro.disconnect();
      term.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const term = termRef.current;
    if (!term) return;
    if (output.length > lastWrittenRef.current) {
      term.write(output.slice(lastWrittenRef.current));
      lastWrittenRef.current = output.length;
    } else if (output.length < lastWrittenRef.current) {
      term.reset();
      term.write(output);
      lastWrittenRef.current = output.length;
    }
  }, [output]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}
