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
          chatMessages.map((message) => (
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
              </div>
              <div className="message-body">
                <ReactMarkdown>{message.content}</ReactMarkdown>
              </div>
            </article>
          ))
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
