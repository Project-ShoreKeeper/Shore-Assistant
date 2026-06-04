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
      convertEol: true,
      cursorBlink: true,
      fontFamily: "Cascadia Code, Consolas, monospace",
      fontSize: 13,
      theme: {
        background: "#ffffff",
        foreground: "#333333",
        cursor: "#333333",
        cursorAccent: "#ffffff",
        selectionBackground: "#cce2ff",
        black: "#000000",
        red: "#cd3131",
        green: "#00bc00",
        yellow: "#949800",
        blue: "#0451a5",
        magenta: "#bc05bc",
        cyan: "#0598bc",
        white: "#555555",
        brightBlack: "#666666",
        brightRed: "#cd3131",
        brightGreen: "#14ce14",
        brightYellow: "#b5ba00",
        brightBlue: "#0451a5",
        brightMagenta: "#bc05bc",
        brightCyan: "#0598bc",
        brightWhite: "#a5a5a5",
      },
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
      lastWrittenRef.current = 0;
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

  return <div ref={containerRef} style={{ width: "100%", height: "100%", overflow: "hidden" }} />;
}
