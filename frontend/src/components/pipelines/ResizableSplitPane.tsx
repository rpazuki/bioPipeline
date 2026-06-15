"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  left: React.ReactNode;
  right: React.ReactNode;
  defaultSplit?: number; // left pane % width, 10–90
  minLeft?: number;
  minRight?: number;
  className?: string;
  // When true the panes grow with their content (the page scrolls) instead of each
  // pane scrolling internally. `minHeight` keeps the split filling the viewport when
  // content is short. Defaults preserve the original fixed-height, inner-scroll layout.
  autoHeight?: boolean;
  minHeight?: number;
}

export default function ResizableSplitPane({
  left,
  right,
  defaultSplit = 50,
  minLeft = 20,
  minRight = 20,
  className = "",
  autoHeight = false,
  minHeight,
}: Props) {
  const [split, setSplit] = useState(defaultSplit);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    function onMouseMove(e: MouseEvent) {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      setSplit(Math.min(100 - minRight, Math.max(minLeft, pct)));
    }

    function onMouseUp() {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [minLeft, minRight]);

  return (
    <div
      ref={containerRef}
      className={`flex ${autoHeight ? "" : "min-h-0"} ${className}`}
      style={autoHeight && minHeight != null ? { minHeight } : undefined}
    >
      {/* Left pane */}
      <div style={{ width: `${split}%` }} className={`min-w-0 ${autoHeight ? "" : "overflow-auto"}`}>
        {left}
      </div>

      {/* Drag handle */}
      <div
        onMouseDown={onMouseDown}
        className="group relative flex w-2 shrink-0 cursor-col-resize items-center justify-center"
        title="Drag to resize"
        aria-hidden
      >
        <div className="h-full w-px bg-slate-200 transition-colors group-hover:bg-cyan-400 group-active:bg-cyan-600" />
        {/* Grip dots */}
        <div className="absolute flex flex-col gap-1 py-1">
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className="h-1 w-1 rounded-full bg-slate-300 group-hover:bg-cyan-400" />
          ))}
        </div>
      </div>

      {/* Right pane */}
      <div style={{ width: `${100 - split}%` }} className={`min-w-0 ${autoHeight ? "" : "overflow-auto"}`}>
        {right}
      </div>
    </div>
  );
}
