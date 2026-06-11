import { useNavigate, useParams } from "react-router-dom";

import { Chronicle } from "./components/Chronicle";
import { CodexSetup } from "./components/CodexSetup";
import { Masthead } from "./components/Masthead";
import { useHealth } from "./hooks/useHealth";

export default function App() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const health = useHealth();
  const phase = sessionId ? "chronicle" : "codex";

  return (
    <div className="shell">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />
      <Masthead phase={phase} health={health} onHome={() => navigate("/")} />

      <div id="main-content">
        {sessionId ? (
          <Chronicle sessionId={sessionId} />
        ) : (
          <CodexSetup
            onStarted={(id, starter) =>
              navigate(`/chronicle/${id}`, { replace: true, state: { starter } })
            }
          />
        )}
      </div>
    </div>
  );
}
