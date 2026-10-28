import { RefObject } from "react";
import type { ChatMessage } from "../types";
import { ComposerBar } from "./ComposerBar";
import { MessageList } from "./MessageList";

type ConversationViewProps = {
  messages: ChatMessage[];
  isLoading: boolean;
  scrollRef: RefObject<HTMLDivElement | null>;
  input: string;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  placeholder: string;
  onShowActivity: () => void;
};

export function ConversationView({
  messages,
  isLoading,
  scrollRef,
  input,
  onInputChange,
  onSubmit,
  placeholder,
  onShowActivity,
}: ConversationViewProps) {
  return (
    <div className="conversation-layout">
      <div className="conversation-left">
        <MessageList
          messages={messages}
          isLoading={isLoading}
          scrollRef={scrollRef}
          onShowActivity={onShowActivity}
        />

        <div className="conversation-bottom">
          <ComposerBar
            input={input}
            onInputChange={onInputChange}
            onSubmit={onSubmit}
            isLoading={isLoading}
            placeholder={placeholder}
            variant="thread"
          />
        </div>
      </div>
    </div>
  );
}
