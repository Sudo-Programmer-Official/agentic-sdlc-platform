import { reactive } from "vue";

export type ProjectContext = {
  projectId: string;
  projectName: string;
  stage: string;
  runStatus: string;
  latestRunId: string;
  activeAgents: number;
  updatedAt: string | null;
};

export const projectContext = reactive<ProjectContext>({
  projectId: "",
  projectName: "No project selected",
  stage: "UNKNOWN",
  runStatus: "IDLE",
  latestRunId: "",
  activeAgents: 0,
  updatedAt: null
});

export function updateProjectContext(update: Partial<ProjectContext>) {
  Object.assign(projectContext, update);
}
