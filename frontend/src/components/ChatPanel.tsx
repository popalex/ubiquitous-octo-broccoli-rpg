import { useRef } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage } from "../types";

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

  return (
    <section className="panel panel-center">
      <div className="panel-header">
        <p className="eyebrow">Live Chronicle</p>
        <h2>The Unfolding Tale</h2>
      </div>

      <div className="chat-log" role="log" aria-live="polite" aria-label="Chat messages">
        {chatMessages.length === 0 ? (
          <div className="empty-state">
            <p>The pages await your tale</p>
            <span>Choose a character template, begin a chronicle, then speak your opening words</span>
          </div>
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

      <div className="composer" aria-live="polite">
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
          <button
            className="btn btn-primary"
            type="button"
            disabled={isBusy || !sessionId}
            onClick={handleSend}
          >
            {isBusy ? "✦ Weaving..." : "▶ Send Turn"}
          </button>
        </div>
      </div>
    </section>
  );
}
