"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  left: React.ReactNode;
  right: React.ReactNode;
  defaultSplit?: number; // left pane % width, 10–90
  minLeft?: number;
  minRight?: number;
  className?: string;
}

export default function ResizableSplitPane({
  left,
  right,
  defaultSplit = 50,
  minLeft = 20,
  minRight = 20,
  className = "",
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
    <div ref={containerRef} className={`flex min-h-0 ${className}`}>
      {/* Left pane */}
      <div style={{ width: `${split}%` }} className="min-w-0 overflow-auto">
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
      <div style={{ width: `${100 - split}%` }} className="min-w-0 overflow-auto">
        {right}
      </div>
    </div>
  );
}
