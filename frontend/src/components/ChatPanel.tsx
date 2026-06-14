import { useRef } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage } from "../types";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";

type Props = {
  chatMessages: ChatMessage[];
  chatInput: string;
  setChatInput: (v: string) => void;
  isBusy: boolean;
  sessionId: string;
  characterName: string;
  statusText: string;
  onSendChat: () => void;
  // Fork a new chronicle from a persisted turn. Omitted while a fork is busy.
  onForkFromTurn?: (turnIndex: number) => void;
  forkingTurn?: number | null;
};

export function ChatPanel({
  chatMessages,
  chatInput,
  setChatInput,
  isBusy,
  sessionId,
  characterName,
  statusText,
  onSendChat,
  onForkFromTurn,
  forkingTurn,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function handleSend() {
    onSendChat();
    textareaRef.current?.focus();
  }

  // Announce only completed assistant turns. A live region on the chat log
  // itself would re-announce every streamed chunk.
  const lastMessage = chatMessages[chatMessages.length - 1];
  const announcement =
    !isBusy && lastMessage && lastMessage.role !== "user"
      ? `${lastMessage.role === "narrator" ? "Game Master" : characterName}: ${lastMessage.content}`
      : "";

  return (
    <section className="panel panel-center">
      <div className="panel-header">
        <p className="eyebrow">Live Chronicle</p>
        <h2>The Unfolding Tale</h2>
      </div>

      <div className="chat-log" role="region" aria-label="Chat messages">
        {chatMessages.length === 0 ? (
          <EmptyState>
            <p>The pages await your tale</p>
            <span>Choose a character template, begin a chronicle, then speak your opening words</span>
          </EmptyState>
        ) : (
          chatMessages.map((message) => {
            // turnsToMessages sets a persisted turn's id to its turn_index;
            // live (unsaved) messages get non-numeric ids, so only persisted
            // turns are forkable until the chronicle is reloaded. Offer forking
            // only on a response turn (assistant/narrator) — the end of an
            // exchange — so a fork never stops on a user line still awaiting a
            // reply. Forks are inclusive of the clicked turn.
            const persistedIndex = /^\d+$/.test(message.id) ? Number(message.id) : null;
            const turnIndex = message.role === "user" ? null : persistedIndex;
            return (
              <article
                key={message.id}
                className={`message message-${message.role}${
                  message.messageType ? ` message-type-${message.messageType}` : ""
                }`}
              >
                <div className="message-role">
                  {message.role === "user"
                    ? "You"
                    : message.role === "narrator"
                      ? "✧ Game Master"
                      : characterName}
                  {onForkFromTurn && turnIndex !== null && (
                    <button
                      type="button"
                      className="message-fork-btn"
                      title="Start a new chronicle branching from here — everything up to and including this point is carried over; the original is untouched"
                      disabled={forkingTurn != null}
                      onClick={() => onForkFromTurn(turnIndex)}
                    >
                      {forkingTurn === turnIndex ? "⑂ Forking…" : "⑂ Fork from here"}
                    </button>
                  )}
                </div>
                <div className="message-body">
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                </div>
              </article>
            );
          })
        )}
      </div>

      <div className="sr-only" role="status">
        {announcement}
      </div>

      <div className="composer">
        <textarea
          ref={textareaRef}
          rows={4}
          placeholder="Inscribe your next action or words..."
          aria-label="Write your response"
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
        />
        <div className="composer-actions">
          <div className="status-note">{statusText}</div>
          <Button type="button" disabled={isBusy || !sessionId} onClick={handleSend}>
            {isBusy ? "✦ Weaving..." : "▶ Send Turn"}
          </Button>
        </div>
      </div>
    </section>
  );
}
