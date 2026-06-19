import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  ChevronRight,
  MessageSquareText,
  Activity
} from "lucide-react";
import { api } from "../../lib/api";
import type { Session, Readiness } from "../../lib/types";

interface SynthesisViewProps {
  session: Session;
  setSession: (s: Session) => void;
  readiness: Readiness | null;
  setReadiness: (r: Readiness | null) => void;
  setView: (v: any) => void;
}

export function SynthesisTab({ session, setSession, readiness, setReadiness, setView }: SynthesisViewProps) {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Array<{ role: "user" | "assistant"; text: string }>>([]);
  const [showJumpLatest, setShowJumpLatest] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const opening = interviewPromptFromReadiness(readiness);

  useEffect(() => {
    setTurns(interviewTurnsFromSession(session, opening));
    setMessage("");
    setShowJumpLatest(false);
  }, [session.id, opening]);

  useEffect(() => {
    if (!showJumpLatest) {
      endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [turns.length]);

  const scrollToLatest = () => {
    setShowJumpLatest(false);
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  };

  const onConversationScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    setShowJumpLatest(distanceFromBottom > 160);
  };

  const send = useMutation({
    mutationFn: () => api.sendSynthesis(session.id, message),
    onSuccess: (result) => {
      const userText = message;
      setSession({ ...session, current_summary: result.brief });
      setReadiness(result.readiness);
      setTurns((current) => [...current, { role: "user", text: userText }, { role: "assistant", text: result.message }]);
      setMessage("");
    }
  });

  const proceed = useMutation({
    mutationFn: (assume: boolean) => api.proceed(session.id, assume),
    onSuccess: (result) => {
      setReadiness(result.readiness);
      if (!result.proceeded) {
        setTurns((current) => [...current, { role: "assistant", text: result.message }]);
      }
      if (result.proceeded) setView("research");
    }
  });

  const interviewCount = interviewTurnCount(session);
  const showOptionalProceed = interviewCount >= 4 || !readiness?.recommended_minimum_questions.length;

  return (
    <section className="flex h-[calc(100vh-113px)] flex-1 flex-col bg-[#f8fafc]">
      <div className="border-b border-awsBorder bg-surface px-6 py-3">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold">
              <MessageSquareText className="h-4 w-4 text-awsOrange" /> Interview
            </div>
            <p className="mt-1 text-xs text-awsTextMuted">Answers feed the brief, research, pricing, architecture, diagrams, and export package.</p>
          </div>
          <span className="border border-awsBorder bg-white px-2 py-1 text-xs text-awsTextMuted">{interviewCount} answers captured</span>
        </div>
      </div>
      <div ref={scrollRef} onScroll={onConversationScroll} className="archway-scroll relative flex-1 overflow-y-auto px-5 py-5">
        <div className="mx-auto space-y-4 pb-4">
          {turns.map((turn, index) => <ConversationBubble key={`${turn.role}-${index}`} role={turn.role} text={turn.text} />)}
          {readiness && showOptionalProceed ? <Checkpoint readiness={readiness} onAssume={() => proceed.mutate(true)} /> : null}
          <div ref={endRef} />
        </div>
        {showJumpLatest ? (
          <button onClick={scrollToLatest} className="sticky bottom-3 mx-auto flex border border-awsBorder bg-white px-3 py-2 text-sm font-semibold text-awsTextSecondary shadow-console hover:border-awsOrange">
            Jump to latest
          </button>
        ) : null}
      </div>
      <div className="sticky bottom-0 border-t border-awsBorder bg-white px-5 py-4 shadow-console">
        <div className="mx-auto max-w-5xl">
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && message.trim() && !send.isPending) {
                send.mutate();
              }
            }}
            className="min-h-28 w-full resize-y border border-awsBorder bg-white p-4 text-base leading-7 text-awsTextPrimary outline-none focus:border-awsOrange"
            placeholder="Answer here. Add constraints, systems, approval rules, numbers, or say what is unknown."
            disabled={send.isPending || proceed.isPending}
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs text-awsTextMuted">Natural language is fine. Short answers are fine too.</div>
            <div className="flex flex-wrap gap-2">
              <Button icon={MessageSquareText} disabled={!message.trim() || send.isPending} onClick={() => send.mutate()} variant="secondary">
                {send.isPending ? "Capturing" : "Send Answer"}
              </Button>
              <Button icon={ChevronRight} disabled={proceed.isPending} onClick={() => proceed.mutate(showOptionalProceed)}>
                {showOptionalProceed ? "Proceed to Research" : "Ask Next Question"}
              </Button>
            </div>
          </div>
          {send.error ? <Banner tone="danger" text={(send.error as Error).message} /> : null}
          {proceed.error ? <Banner tone="danger" text={(proceed.error as Error).message} /> : null}
        </div>
      </div>
    </section>
  );
}

function Checkpoint({ readiness, onAssume }: { readiness: Readiness; onAssume: () => void }) {
  return (
    <div className="border border-awsBorder bg-white p-4">
      <div className="mb-2 flex items-center gap-2 font-semibold">
        <AlertTriangle className="h-5 w-5 text-awsWarning" /> Optional checks before research
      </div>
      <p className="text-sm text-awsTextSecondary">Archway can proceed with visible assumptions, or you can answer any remaining items first.</p>
      <ul className="mt-3 space-y-2 text-sm text-awsTextSecondary">
        {readiness.recommended_minimum_questions.slice(0, 3).map((question) => <li key={question.id}>{question.prompt}</li>)}
      </ul>
      <Button icon={ChevronRight} onClick={onAssume} className="mt-4">Let Archway assume and proceed</Button>
    </div>
  );
}

function ConversationBubble({ role, text }: { role: "user" | "assistant"; text: string }) {
  const Icon = role === "assistant" ? Bot : MessageSquareText;
  return (
    <div className={`mx-auto flex max-w-5xl gap-3 ${role === "user" ? "justify-end" : "justify-start"}`}>
      <div className={`w-fit max-w-[82%] border p-4 ${role === "user" ? "border-awsBorder bg-awsPanelSoft" : "border-awsOrange/40 bg-surface"}`}>
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <Icon className="h-4 w-4 text-awsOrange" /> {role === "assistant" ? "Archway" : "You"}
        </div>
        <div className="whitespace-pre-wrap text-sm leading-6 text-awsTextSecondary">{text}</div>
      </div>
    </div>
  );
}

function Button({ children, icon: Icon, variant = "primary", disabled, onClick, className = "" }: { children?: React.ReactNode; icon?: typeof Activity; variant?: "primary" | "secondary" | "ghost"; disabled?: boolean; onClick?: () => void; className?: string }) {
  const styles = variant === "primary" ? "border-awsOrange bg-awsOrange text-[#111827] hover:bg-[#ffad33]" : variant === "secondary" ? "border-awsBorder bg-awsPanelSoft text-awsTextPrimary hover:border-awsOrange" : "border-transparent bg-transparent text-awsTextSecondary hover:border-awsBorder";
  return (
    <button disabled={disabled} onClick={onClick} className={`inline-flex min-h-10 items-center justify-center gap-2 border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}>
      {Icon ? <Icon className="h-4 w-4" /> : null}
      {children}
    </button>
  );
}

function Banner({ tone, text }: { tone: "info" | "warning" | "danger"; text: string }) {
  const toneClass =
    tone === "danger"
      ? "border-awsDanger/50 bg-[#fff1f2] text-awsDanger"
      : tone === "warning"
        ? "border-awsOrange/50 bg-[#fff8eb] text-awsTextSecondary"
        : "border-awsInfo/50 bg-[#eef6ff] text-awsTextSecondary";
  return <div className={`border p-4 text-sm ${toneClass}`}>{text}</div>;
}

function interviewTurnCount(session: Session) {
  const profile = session.current_summary?.use_case_profile as { interview?: { turn_count?: number; answered?: string[] } } | undefined;
  return profile?.interview?.turn_count ?? profile?.interview?.answered?.length ?? 0;
}

function interviewPromptFromReadiness(readiness: Readiness | null) {
  const question = readiness?.recommended_minimum_questions?.[0];
  if (!question) {
    return "I have enough to shape the first research pass. Add any constraints you want captured before research, or proceed when ready.";
  }
  return [
    "Let’s tighten the brief before research.",
    "",
    question.prompt,
    "",
    `Why it matters: ${question.why_it_matters}`,
    "",
    `Useful answer styles: ${question.options.join(" | ")}`
  ].join("\n");
}

function interviewTurnsFromSession(session: Session, opening: string) {
  const turns: Array<{ role: "user" | "assistant"; text: string }> = [{ role: "user", text: session.initial_use_case }];
  const assumptions = session.current_summary?.assumptions ?? [];
  const capturedAnswers = assumptions
    .map((item) => {
      const match = item.text.match(/^Interview answer for '(.+)': ([\s\S]+)$/);
      return match ? { question: match[1], answer: match[2] } : null;
    })
    .filter((item): item is { question: string; answer: string } => Boolean(item));
  capturedAnswers.forEach((item, index) => {
    turns.push({ role: "assistant", text: index === 0 ? item.question : `Next question: ${item.question}` });
    turns.push({ role: "user", text: item.answer });
  });
  turns.push({ role: "assistant", text: opening });
  return turns;
}
