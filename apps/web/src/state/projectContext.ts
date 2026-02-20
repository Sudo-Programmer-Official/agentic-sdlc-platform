import { reactive } from "vue";

export type ProjectContext = {
  projectId: string;
  projectName: string;
  stage: string;
  runStatus: string;
  latestRunId: string;
  activeAgents: number;
  updatedAt: string | null;
  hasActiveRun: boolean;
  architectureRefreshNeeded: boolean;
  planRefreshNeeded: boolean;
  testRefreshNeeded: boolean;
};

export const projectContext = reactive<ProjectContext>({
  projectId: "",
  projectName: "No project selected",
  stage: "UNKNOWN",
  runStatus: "IDLE",
  latestRunId: "",
  activeAgents: 0,
  updatedAt: null,
  hasActiveRun: false,
  architectureRefreshNeeded: false,
  planRefreshNeeded: false,
  testRefreshNeeded: false
});

export function updateProjectContext(update: Partial<ProjectContext>) {
  Object.assign(projectContext, update);
}
