import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { ReviewWorkspace } from "@/components/ReviewWorkspace";
import { isSafeId } from "@/lib/validate";
import { serverAccount } from "@/lib/session";

export const metadata: Metadata = { title: "New review · reScrub" };

// /review opens the setup steps (sign-in required when a backend is configured);
// /review?session=<id> reopens one of your recordings (the page puts it there after an upload, so a
// refresh keeps it); /review?demo=1 opens the public demonstration directly.
export default async function ReviewPage({ searchParams }: PageProps<"/review">) {
  const { demo, session } = await searchParams;
  const startInDemo = demo === "1";
  const resumeSessionId = !startInDemo && isSafeId(session) ? session : null;
  let account = null;
  if (!startInDemo && process.env.NEXT_PUBLIC_API_BASE_URL) {
    const found = await serverAccount();
    if (found === null) {
      redirect(`/login?next=${encodeURIComponent(resumeSessionId ? `/review?session=${resumeSessionId}` : "/review")}`);
    }
    account = found === "unchecked" ? null : found;
  }
  // The key makes switching between /review, a recording and the demonstration start fresh.
  return (
    <ReviewWorkspace
      key={startInDemo ? "demo" : (resumeSessionId ?? "setup")}
      startInDemo={startInDemo}
      account={account}
      resumeSessionId={resumeSessionId}
    />
  );
}
