"use client";

import JobQueuePanel from "@/components/pipelines/JobQueuePanel";
import { usePipeline } from "@/components/pipelines/PipelineContext";

export default function HomePage() {
  const { setStatus } = usePipeline();

  return (
    <div className="grid gap-4 p-5">
      <JobQueuePanel onStatus={setStatus} />
    </div>
  );
}
