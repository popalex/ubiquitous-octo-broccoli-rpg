import ReactMarkdown from "react-markdown";
import type { ChatMessage } from "../types";

type Props = {
  chatMessages: ChatMessage[];
  chatInput: string;
  setChatInput: (v: string) => void;
  isBusy: boolean;
  sessionId: string;
  characterName: string;
  worldName: string;
  gmEnabled: boolean;
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
  worldName,
  gmEnabled,
  statusText,
  onSendChat,
}: Props) {
  return (
    <section className="panel panel-center">
      <div className="panel-header">
        <p className="eyebrow">Live Chronicle</p>
        <h2>The Unfolding Tale</h2>
      </div>

      <div className="session-meta">
        <div>
          <span className="meta-label">Protagonist</span>
          <strong>{characterName || "—"}</strong>
        </div>
        <div>
          <span className="meta-label">Chronicle</span>
          <strong>{sessionId ? `#${sessionId.slice(0, 8)}` : "Awaiting"}</strong>
        </div>
        <div>
          <span className="meta-label">Realm</span>
          <strong>{worldName || "—"}</strong>
        </div>
        {gmEnabled && (
          <div>
            <span className="meta-label">Mode</span>
            <strong className="gm-badge">✧ GM</strong>
          </div>
        )}
      </div>

      <div className="chat-log">
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

      <div className="composer">
        <textarea
          rows={4}
          placeholder="Inscribe your next action or words..."
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
        />
        <div className="composer-actions">
          <div className="status-note">{statusText}</div>
          <button
            className="btn btn-primary"
            type="button"
            disabled={isBusy || !sessionId}
            onClick={onSendChat}
          >
            {isBusy ? "✦ Weaving..." : "▶ Send Turn"}
          </button>
        </div>
      </div>
    </section>
  );
}
