import { assetUrl } from "../utils";

const SOURCES = ["Demo data loaded directly into Redis"];

function AgentIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 18 18" fill="none">
      <rect x="2" y="5" width="14" height="10" rx="2.5" fill="#163341" />
      <circle cx="6.5" cy="10" r="1.3" fill="white" />
      <circle cx="11.5" cy="10" r="1.3" fill="white" />
      <rect x="7" y="1.5" width="4" height="3.5" rx="1.2" fill="#FF4438" />
      <rect x="8.5" y="4" width="1" height="1.5" fill="#163341" />
    </svg>
  );
}

export function FlowStrip() {
  return (
    <div className="flow-strip">
      <div className="flow-strip-pipeline">
        {/* Sources */}
        <div className="flow-zone">
          <div className="flow-sources">
            {SOURCES.map((name) => (
              <span key={name} className="flow-source-dot" title={name} />
            ))}
          </div>
          <span className="flow-zone-label">Sources</span>
        </div>

        <div className="flow-connector" />

        {/* RDI */}
        <div className="flow-zone">
          <img src={assetUrl("/icons/RDI-64-duotone.svg")} alt="RDI" className="flow-node" />
          <span className="flow-zone-label">RDI</span>
        </div>

        <div className="flow-connector" />

        {/* Redis */}
        <div className="flow-zone">
          <img src={assetUrl("/RedisLogo.png")} alt="Redis" className="flow-redis-icon" />
        </div>

        <div className="flow-connector" />

        {/* Context Retriever */}
        <div className="flow-zone">
          <img
            src={assetUrl("/icons/context-retriever-64-duotone.svg")}
            alt="Context Retriever"
            className="flow-node"
          />
          <span className="flow-zone-label">Retriever</span>
        </div>

        <div className="flow-connector" />

        {/* Agent column: LangCache / Agent / Memory */}
        <div className="flow-agent-col">
          <div className="flow-zone">
            <img
              src={assetUrl("/icons/langcache-64-duotone.svg")}
              alt="LangCache"
              className="flow-node"
            />
            <span className="flow-zone-label">Cache</span>
          </div>
          <div className="flow-vconnector" />
          <div className="flow-zone">
            <AgentIcon className="flow-agent-icon" />
            <span className="flow-zone-label">Agent</span>
          </div>
          <div className="flow-vconnector" />
          <div className="flow-zone">
            <img
              src={assetUrl("/icons/agent-memory-64-duotone.svg")}
              alt="Agent Memory"
              className="flow-node"
            />
            <span className="flow-zone-label">Memory</span>
          </div>
        </div>
      </div>
    </div>
  );
}
