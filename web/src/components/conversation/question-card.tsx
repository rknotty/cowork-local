import { useId, useState } from "react";
import type { FormEvent, ReactElement } from "react";
import { postAnswer } from "../../api/api-client";
import { useAlerts } from "../../state/alerts-context";
import { useSession } from "../../state/session-context";
import type { QuestionItem } from "../../state/session-state";

interface QuestionCardProps {
  item: QuestionItem;
}

interface AnswerFormProps {
  item: QuestionItem;
  isSubmitting: boolean;
  onAnswer: (answer: string) => void;
}

function AnswerForm({ item, isSubmitting, onAnswer }: AnswerFormProps): ReactElement {
  const [draft, setDraft] = useState("");
  const inputId = useId();
  const trimmedDraft = draft.trim();

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (trimmedDraft.length > 0) {
      onAnswer(trimmedDraft);
    }
  };

  return (
    <>
      {item.options.length > 0 && (
        <div className="button-row">
          {item.options.map((option) => (
            <button
              key={option}
              type="button"
              className="button"
              disabled={isSubmitting}
              onClick={() => onAnswer(option)}
            >
              {option}
            </button>
          ))}
        </div>
      )}
      <form className="inline-form" onSubmit={handleSubmit}>
        <label htmlFor={inputId}>Your own answer</label>
        <input
          id={inputId}
          type="text"
          value={draft}
          disabled={isSubmitting}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button
          type="submit"
          className="button button-primary"
          disabled={isSubmitting || trimmedDraft.length === 0}
        >
          Send answer
        </button>
      </form>
    </>
  );
}

/** A question from the agent, answered with one of its options or free text. */
export function QuestionCard({ item }: QuestionCardProps): ReactElement {
  const { sessionId, dispatch } = useSession();
  const { reportError } = useAlerts();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const headingId = useId();

  const handleAnswer = async (answer: string): Promise<void> => {
    setIsSubmitting(true);
    try {
      await postAnswer(sessionId, item.questionId, answer);
      dispatch({ type: "question_answered", questionId: item.questionId, answer });
    } catch (thrown) {
      reportError(thrown);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="card prompt-card" aria-labelledby={headingId}>
      <h3 id={headingId} className="card-heading">
        Question
      </h3>
      <p className="card-question">{item.question}</p>
      {item.answer === null ? (
        <AnswerForm
          item={item}
          isSubmitting={isSubmitting}
          onAnswer={(answer) => void handleAnswer(answer)}
        />
      ) : (
        <p className="card-line" role="status">
          You answered: {item.answer}
        </p>
      )}
    </section>
  );
}
