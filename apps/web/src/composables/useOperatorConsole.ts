import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import type { OperatorAction, OperatorReference, OperatorResponse } from "../api/lifecycle";
import { sendOperatorMessage } from "../api/lifecycle";
import { projectContext } from "../state/projectContext";

export type PromptChip = {
  label: string;
  prompt: string;
};

export type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  answer: string;
  status?: string;
  groundingTools?: string[];
  references?: OperatorReference[];
  actions?: OperatorAction[];
};

const starterPrompts: PromptChip[] = [
  { label: "Why did the latest run fail?", prompt: "Why did the latest run fail?" },
  { label: "Explain the latest patch", prompt: "Explain the latest patch" },
  { label: "Compare the last two runs", prompt: "Compare the last two runs" },
  { label: "Show workspace status", prompt: "Show workspace status" },
  { label: "Show project health", prompt: "Show project health" },
  { label: "Show repo map", prompt: "Show repo map" },
  { label: "Find the login component", prompt: "Find the login component" },
];

function introMessage(projectName: string): ChatMessage {
  return {
    id: `intro-${projectName || "system"}`,
    role: "assistant",
    answer:
      projectName && projectName !== "No project selected"
        ? `AI Operator is ready for ${projectName}. Ask about the current project, latest run, patch explanations, run comparison, project health, workspace state, or repo structure.`
        : "AI Operator is ready. Open a project to inspect runs, artifacts, project health, workspace state, or the repo map.",
    actions: starterPrompts.map((item) => ({
      label: item.label,
      type: "prompt",
      prompt: item.prompt,
    })),
  };
}

export function useOperatorConsole() {
  const route = useRoute();
  const router = useRouter();

  const loading = ref(false);
  const draft = ref("");
  const messages = ref<ChatMessage[]>([introMessage(projectContext.projectName)]);

  const currentProjectId = computed(() => {
    const fromRoute = route.params.projectId;
    return typeof fromRoute === "string" && fromRoute ? fromRoute : projectContext.projectId || "";
  });
  const currentProjectName = computed(() => projectContext.projectName || "No project selected");
  const currentRunId = computed(() => {
    const fromRoute = route.params.runId;
    if (typeof fromRoute === "string" && fromRoute) return fromRoute;
    return projectContext.latestRunId || "";
  });
  const currentArtifactId = computed(() => {
    const fromRoute = route.params.artifactId;
    return typeof fromRoute === "string" && fromRoute ? fromRoute : "";
  });
  const currentRunStatus = computed(() => projectContext.runStatus || "IDLE");

  watch(
    () => currentProjectId.value,
    () => {
      messages.value = [introMessage(currentProjectName.value)];
      draft.value = "";
    }
  );

  function shortId(value?: string | null) {
    return value ? value.slice(0, 8) : "—";
  }

  function appendMessage(message: ChatMessage) {
    messages.value = [...messages.value, message];
  }

  function toAssistantMessage(response: OperatorResponse): ChatMessage {
    return {
      id: `assistant-${Date.now()}`,
      role: "assistant",
      answer: response.answer,
      status: response.status,
      groundingTools: response.grounding_tools || [],
      references: response.references || [],
      actions: response.actions || [],
    };
  }

  async function submit(prompt = draft.value) {
    const message = prompt.trim();
    if (!message || loading.value || !currentProjectId.value) return;

    appendMessage({
      id: `user-${Date.now()}`,
      role: "user",
      answer: message,
    });
    draft.value = "";
    loading.value = true;

    try {
      const response = await sendOperatorMessage({
        project_id: currentProjectId.value,
        message,
        context: {
          run_id: currentRunId.value || undefined,
          artifact_id: currentArtifactId.value || undefined,
        },
      });
      appendMessage(toAssistantMessage(response));
    } catch (error: any) {
      appendMessage({
        id: `assistant-error-${Date.now()}`,
        role: "assistant",
        answer: error?.message || "The operator could not complete that request.",
        status: "error",
        actions: starterPrompts.map((item) => ({ label: item.label, type: "prompt", prompt: item.prompt })),
      });
    } finally {
      loading.value = false;
    }
  }

  function runPrompt(prompt: string) {
    draft.value = prompt;
    void submit(prompt);
  }

  function openReference(reference: OperatorReference) {
    if (reference.url) {
      window.open(reference.url, "_blank", "noopener,noreferrer");
      return;
    }
    if (reference.path) {
      void router.push(reference.path);
    }
  }

  function runAction(action: OperatorAction) {
    if (action.url) {
      window.open(action.url, "_blank", "noopener,noreferrer");
      return;
    }
    if (action.path) {
      void router.push(action.path);
      return;
    }
    if (action.prompt) {
      runPrompt(action.prompt);
    }
  }

  return {
    currentArtifactId,
    currentProjectId,
    currentProjectName,
    currentRunId,
    currentRunStatus,
    draft,
    loading,
    messages,
    shortId,
    starterPrompts,
    submit,
    runPrompt,
    openReference,
    runAction,
  };
}
