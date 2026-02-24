import { useState } from "react";

interface Props {
  src: string;
}

export default function ScreenshotViewer({ src }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <div className="animate-fade-in">
        <button
          onClick={() => setExpanded(true)}
          className="group relative block overflow-hidden rounded-xl border border-edge transition-all hover:border-cyan/30"
        >
          <img
            src={src}
            alt="Page screenshot"
            className="max-h-48 w-full object-cover object-top"
          />
          <div className="absolute inset-0 flex items-center justify-center bg-void/60 opacity-0 transition-opacity group-hover:opacity-100">
            <span className="rounded-md bg-slab/90 px-3 py-1.5 font-mono text-xs text-cyan">
              Click to expand
            </span>
          </div>
        </button>
      </div>

      {/* Modal */}
      {expanded && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-void/90 backdrop-blur-sm"
          onClick={() => setExpanded(false)}
        >
          <div className="relative max-h-[90vh] max-w-[90vw] overflow-auto rounded-xl border border-edge shadow-2xl">
            <img src={src} alt="Page screenshot (full)" className="block" />
            <button
              onClick={() => setExpanded(false)}
              className="absolute right-3 top-3 rounded-md bg-slab/90 px-2 py-1 font-mono text-xs text-dim hover:text-text"
            >
              ESC
            </button>
          </div>
        </div>
      )}
    </>
  );
}
